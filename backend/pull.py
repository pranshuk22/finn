"""Pull side: the promise ledger, bull and bear, and Ask. Primary sources only.

Guards against made-up answers:
1. The model sees only text extracted from the company's own transcripts, or numbers computed here.
2. Every claim carries a document and page, or a fact id.
3. Every quote is checked against the source text in Python; claims whose quote is not found are dropped.
"""

import json
import math
import os
import re
import threading
import time
from datetime import date, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from backend import analytics as A
from backend import db, llm
from backend.config import FINANCIALS, PORTFOLIO, USER_AGENT
from backend.sources import pdf, screener

N_TRANSCRIPTS = 4
_jobs: dict[str, dict[str, str]] = {}
_lock = threading.Lock()


class UnknownTicker(Exception):
    pass


# ---------- data plumbing ----------


def ensure_company(ticker: str) -> None:
    """Fetch Screener (and NSE results) on first sight of a ticker, so research works for any symbol."""
    with db.session() as c:
        if c.execute("SELECT 1 FROM companies WHERE ticker=?", (ticker,)).fetchone():
            return
    from backend.jobs.refresh import refresh_results, store_screener  # avoid import cycle at module load

    try:
        page = screener.fetch(ticker)
    except screener.NotFound:
        raise UnknownTicker(ticker) from None
    store_screener(ticker, page)
    try:
        from backend.sources.nse import NSE

        refresh_results(NSE(), [ticker])
    except Exception:
        pass  # research still works from Screener alone


def _period_date(p: str) -> date | None:
    for fmt in ("%b %Y", "%B %Y", "%Y"):
        try:
            return datetime.strptime(p.strip(), fmt).date()
        except ValueError:
            continue
    return None


def document_list(c, ticker: str) -> list[dict]:
    rows = c.execute(
        "SELECT kind, period, url, pages IS NOT NULL AS loaded FROM documents WHERE ticker=?", (ticker,)
    ).fetchall()
    rows = sorted(rows, key=lambda r: _period_date(r["period"]) or date.min, reverse=True)
    tr = [dict(r) for r in rows if r["kind"] == "transcript"][:N_TRANSCRIPTS]
    ar = [dict(r) for r in rows if r["kind"] == "annual_report"][:1]
    return tr + ar


_TRANSCRIPT_RX = re.compile(r"transcript", re.I)


def sync_nse_transcripts(ticker: str) -> None:
    """Use the exchange's own transcript filings as the primary source.

    Screener's links can be wrong: for TCS its "Jul 2026" transcript pointed to the Jul 2025 call on
    tcs.com, which also answers 403 to scripts (RESEARCH R7).
    """
    from backend.sources.nse import NSE

    today = date.today()
    try:
        items = NSE().announcements(ticker, today.replace(year=today.year - 1), today)
    except Exception:
        return
    seen = set()
    with db.session() as c:
        for f in items:  # newest first
            blob = f["nse_label"] + " " + f["text"]
            if not f["pdf_url"] or not _TRANSCRIPT_RX.search(blob) or re.search(r"audio|recording", blob, re.I):
                continue
            period = datetime.fromisoformat(f["an_dt"]).strftime("%b %Y")
            if period in seen:
                continue
            seen.add(period)
            old = c.execute(
                "SELECT url FROM documents WHERE ticker=? AND kind='transcript' AND period=?", (ticker, period)
            ).fetchone()
            if old and old["url"] == f["pdf_url"]:
                continue
            # Some companies file only a cover letter saying the transcript is on their website: L&T's NSE
            # "transcripts" are one page of about 1,800 characters. Storing one replaced Screener's link to the real
            # call for that month and left L&T's ledger with one call (3 Nov). Only a readable transcript is kept.
            try:
                pages = pdf.pages(pdf.download(f["pdf_url"]))
            except Exception:
                continue
            if sum(len(p) for p in pages) < 2000:
                continue
            c.execute(
                "INSERT OR REPLACE INTO documents(ticker, kind, period, url, pages) VALUES(?,?,?,?,?)",
                (ticker, "transcript", period, f["pdf_url"], json.dumps(pages)),
            )
        db.set_meta(c, f"nse_transcripts_synced:{ticker}", db.now_iso())


def load_transcripts(ticker: str) -> list[dict]:
    """Latest transcripts, oldest first, each as {period, url, pages}."""
    with db.session() as c:
        synced = db.get_meta(c, f"nse_transcripts_synced:{ticker}")
    if not synced:
        sync_nse_transcripts(ticker)
    with db.session() as c:
        docs = [d for d in document_list(c, ticker) if d["kind"] == "transcript"]
    out = []
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for d in docs:
            with db.session() as c:
                row = c.execute(
                    "SELECT pages FROM documents WHERE ticker=? AND kind='transcript' AND period=?",
                    (ticker, d["period"]),
                ).fetchone()
            if row and row["pages"]:
                pages = json.loads(row["pages"])
            else:
                try:
                    pages = pdf.pages(pdf.download(d["url"], client))
                except Exception:
                    continue
                if sum(len(p) for p in pages) < 2000:  # scanned or empty PDF
                    continue
                with db.session() as c:
                    c.execute(
                        "UPDATE documents SET pages=? WHERE ticker=? AND kind='transcript' AND period=?",
                        (json.dumps(pages), ticker, d["period"]),
                    )
            out.append({"period": d["period"], "url": d["url"], "pages": pages})
    out.sort(key=lambda d: _period_date(d["period"]) or date.min)
    return out


def load_annual_report(ticker: str, fetch: bool = True) -> dict | None:
    """The latest annual report as {period, url, pages}. They run to hundreds of pages (RELIANCE's 2026 report is
    several hundred), so they are read once, stored, and then searched page by page; never sent whole to a model."""
    with db.session() as c:
        row = next((d for d in document_list(c, ticker) if d["kind"] == "annual_report"), None)
        if not row:
            return None
        stored = c.execute(
            "SELECT pages FROM documents WHERE ticker=? AND kind='annual_report' AND period=?", (ticker, row["period"])
        ).fetchone()
    if stored and stored["pages"]:
        return {"period": row["period"], "url": row["url"], "pages": json.loads(stored["pages"])}
    if not fetch:
        return None
    try:
        pages = pdf.pages(pdf.download(row["url"]))
    except Exception:
        return None
    if sum(len(p) for p in pages) < 20000:  # scanned, or not the report
        return None
    with db.session() as c:
        c.execute(
            "UPDATE documents SET pages=? WHERE ticker=? AND kind='annual_report' AND period=?",
            (json.dumps(pages), ticker, row["period"]),
        )
    return {"period": row["period"], "url": row["url"], "pages": pages}


_STOP = set(
    "the and for with what how why who when which does did has have had are was were its their this that from into "
    "about over under more less than any all much many company companies year years last latest tell explain show "
    "give list report annual business there they them our your between during".split()
)


def report_pages(doc: dict, question: str, k: int = 6) -> list[int]:
    """Pages of a long report most likely to answer the question, 1-based, best first. Plain keyword scoring:
    rare words count more (log inverse document frequency), and each word is matched on its first six letters so
    "auditor" also finds "audit" and "auditors". On the TITAN 2026 report, "Who is the auditor?" ranks the
    Independent Auditor's Report pages first."""
    kept = [w for w in re.findall(r"[a-z]{3,}", question.lower()) if w not in _STOP]
    words = list(dict.fromkeys(w[:6] for w in kept))
    if not words:
        return []
    low = [re.sub(r"\s+", " ", p.lower()) for p in doc["pages"]]
    n = len(low)
    weight = {w: math.log(n / (1 + sum(1 for p in low if w in p))) for w in words}
    # Two question words side by side on a page count far more than either alone: DIXON's "Statutory Auditors
    # M/s S.N. Dhawan" page ranked third behind audit committee pages that say "auditor" more often.
    phrases = [re.compile(rf"\b{a[:6]}\w*\W+{b[:6]}") for a, b in zip(kept, kept[1:], strict=False)]
    scored = []
    for i, p in enumerate(low):
        score = sum(weight[w] * min(p.count(w), 5) for w in words if weight[w] > 0)
        score += sum(10 * min(len(ph.findall(p)), 3) for ph in phrases)
        if score > 0:
            scored.append((score, i + 1))
    return [pg for _, pg in sorted(scored, reverse=True)[:k]]


def _match_doc(source: str | None, docs: list[dict]) -> dict | None:
    """The model echoes headers like "Apr 2026 call"; match on the period inside it."""
    if not source:
        return None
    return next((d for d in docs if d["period"].lower() in source.lower()), None)


def _paged(doc: dict) -> str:
    return "\n".join(f"[page {i + 1}]\n{p}" for i, p in enumerate(doc["pages"]))


# ---------- quote verification ----------

# Ligature glyphs as they come out of some transcript PDFs. U+01AF shows up where "ff" was set as a
# ligature in the TCS transcripts ("eƯorts" for "efforts").
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "Ư": "ff"}


def _norm(s: str) -> str:
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    s = re.sub(r"[^a-z0-9%]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _fuzzy_in(q_tokens: list[str], text: str, threshold: float = 0.9) -> bool:
    """True if some window of `text` contains at least `threshold` of the quote's words, in order."""
    from difflib import SequenceMatcher

    t = text.split()
    n = len(q_tokens)
    for i in range(0, max(1, len(t) - n + 1)):
        if t[i] not in q_tokens[:3]:
            continue
        m = SequenceMatcher(None, q_tokens, t[i : i + n + 3], autojunk=False)
        if sum(b.size for b in m.get_matching_blocks()) / n >= threshold:
            return True
    return False


def verify_quote(quote: str, doc: dict, page: int | None) -> int | None:
    """Page where the quote really appears (pages are 1-based), or None if it is not in the document.

    Single pages are searched first, nearest the claimed page; then each page joined with the next,
    since a quote may cross a page break.
    """
    q = _norm(quote)
    if len(q) < 15:
        return None
    pages = [_norm(p) for p in doc["pages"]]
    order = list(range(len(pages)))
    if page:
        order.sort(key=lambda i: abs(i - (page - 1)))
    for i in order:
        if q in pages[i]:
            return i + 1
    for i in order:
        joined = pages[i] + " " + (pages[i + 1] if i + 1 < len(pages) else "")
        if q in joined:
            return i + 1
    # Fallback for small differences (a fixed typo, a dropped filler word). 90% of the quote's words
    # must appear in order, so an invented quote still fails.
    qt = q.split()
    for i in order:
        joined = pages[i] + " " + (pages[i + 1] if i + 1 < len(pages) else "")
        if _fuzzy_in(qt, joined):
            return i + 1
    return None


# ---------- promise ledger ----------


class LedgerItem(BaseModel):
    source: str = Field(description="The call the promise was made on, as in its header, e.g. 'Jan 2026'")
    metric: str = Field(description="Short name, e.g. 'Operating margin', 'Revenue growth', 'Capex'")
    metric_key: Literal["revenue_growth", "operating_margin", "pat_growth", "capex", "other"]
    target: str = Field(description="The target in plain words, e.g. '26% to 28%' or 'double-digit'")
    target_low: float | None = None
    target_high: float | None = None
    unit: Literal["percent", "rs_crore", "bps", "other"] = "other"
    timeframe: str = Field(description="As stated, e.g. 'FY27', 'next 18 to 24 months', 'long term'")
    due: str | None = Field(None, description="ISO date when the timeframe ends, or null if open-ended")
    quote: str = Field(description="Exact words from the source call, 10 to 40 words")
    page: int
    speaker: str | None = None
    kind: Literal["numeric", "qualitative"]
    status: Literal["delivered", "missed", "revised", "dropped", "pending", "unclear"]
    note: str = Field(description="At most 20 words, plain English")
    evidence_quote: str | None = Field(None, description="Exact words from a LATER call, 10 to 40 words")
    evidence_source: str | None = Field(None, description="Which later call, as in its header")
    evidence_page: int | None = None


class Ledger(BaseModel):
    items: list[LedgerItem]


_LEDGER_SYSTEM = """You audit an Indian listed company's management: what they promised on earnings calls, and what
happened after. You get up to four call transcripts in date order and a table of reported numbers.

Step 1. From each call, list the forward-looking commitments management made about the company itself: guidance
on revenue or growth, margins, profit, capex, capacity, debt, order book, launches, and dated plans. Each must have
a target or a timeframe. Exclude client case studies, industry or macro commentary, anything said by an analyst,
past results, and vague aspirations with neither a target nor a timeframe. At most 6 per call, the most specific;
when the company reports several segments, cover each segment's guidance, not only the group's.

Step 2. For each one, judge what happened using only the LATER calls and the numbers:
- delivered: a later call or the numbers state the result was achieved: the number reached, or the event done.
  Progress, a plan restated, a deal size repeated or "our fastest growing business" is unclear, not delivered.
- missed: the timeframe has passed and it did not happen, or management said it would not.
- revised: a later call changed the target or the timeframe.
- dropped: no later call mentions it at all.
- pending: the timeframe has not ended, or it comes from the latest call.
- unclear: later calls mention it but do not settle it.

Rules:
- quote and evidence_quote: copy 10 to 40 consecutive words exactly as written. Do not paraphrase or fix typos.
- page and evidence_page: the number in the [page N] marker above the quote, in that call.
- delivered, missed and revised need evidence_quote from a later call.
- due: the date the timeframe ends. FY27 runs from 1 April 2026 to 31 March 2027. 'Next quarter' is relative to the
  call it was said on. Null for 'long term' or open-ended.
- target_low and target_high: numbers only, in the unit given. A single number goes in both.
- Use only these texts. A CAGR is a yearly rate: write "23% a year over five years", never "grew 23% over five years".
Keep units exactly as in the facts (%, crore, days, points).
Do not use anything you know about the company from elsewhere."""


def _numbers_table(c, ticker: str) -> str:
    rc_rows = c.execute("SELECT period_end FROM results WHERE ticker=? ORDER BY period_end", (ticker,)).fetchall()
    tr = A.trajectory(c, ticker)
    lines = ["Reported numbers (Rs crore, from filings and Screener; computed, not estimated):"]
    for label in ("Revenue", "Margin %", "Net profit"):
        q = tr["quarterly"].get(label) or []
        if q:
            lines.append(f"Quarterly {label}: " + ", ".join(f"{r['period']} {r['value']}" for r in q))
        a = tr["annual"].get(label) or []
        if a:
            lines.append(f"Annual {label}: " + ", ".join(f"{r['period']} {r['value']}" for r in a))
    seg = A.segment_history(c, ticker)
    if seg:
        lines.append(
            "Segment revenue / segment result (profit before interest and tax) by quarter, from the results filings:"
        )
        for name, qs in seg.items():
            lines.append(f"{name}: " + ", ".join(f"{q['quarter']} {q['revenue']} / {q['result']}" for q in qs))
    if rc_rows:
        lines.append(f"Latest reported quarter ends {rc_rows[-1]['period_end']}.")
    return "\n".join(lines)


def _latest_quarter_end(c, ticker: str) -> date | None:
    r = c.execute("SELECT MAX(period_end) FROM results WHERE ticker=?", (ticker,)).fetchone()[0]
    if r:
        return date.fromisoformat(r)
    q = A.trajectory(c, ticker)["quarterly"].get("Revenue") or []
    return _period_date(q[-1]["period"]) if q else None


def _shortfall(actual: float, low: float) -> str:
    # HAL guided 7% to 8% for FY26 and reported "an increase of 7%"; Screener's figures give 6.8%. Stating the
    # gap lets the reader judge a near miss instead of reading a bare "missed".
    return f", {round(low - actual, 1)} points below the {low:g}% low end" if actual < low else ""


# Words that describe a company-wide revenue, profit or margin figure. Anything else left in a promise's metric
# names a part of the business: "Business Banking MSME loan growth" (HDFCBANK) or "jewellery revenue CAGR"
# (TITAN) were judged against company revenue before 31 Oct, which an independent review caught.
_GENERIC = re.compile(
    r"\b(total|overall|company|consolidated|group|revenue|revenues|sales|top[- ]?line|income|growth|grow|rate|"
    r"cagr|yoy|annual|annualised|margin|margins|operating|ebitda|ebit|pbdit|pat|net|profit|profits|the|of|in|"
    r"for|and|level|guidance|target|percent|double[- ]digit|single[- ]digit|exit|range|long|term|full|year|"
    r"value)\b",
    re.I,
)


def _company_level(metric: str) -> bool:
    return not re.sub(r"[^a-z]", "", _GENERIC.sub("", metric.lower()))


# ---------- checking promises against the filed results ----------
#
# A margin promise names its definition, and each one can be rebuilt from the line items in the results filing:
#   EBIT   = PBT + finance costs - other income
#   EBITDA = PBT + finance costs + depreciation - other income
#   PBDIT  = PBT + finance costs + depreciation (other income included; Asian Paints guides on this)
# Indian IT services companies say "operating margin" for EBIT: TCS's Q2 FY27 filing gives (18,638 + 252 - 1,337)
# / 73,188 = 23.98%, and on the Oct 2026 call TCS said "operating margin of 24%"; Infosys, 20.98% and "21%".

_MARGIN_NAME = {
    "ebit": "EBIT margin",
    "ebitda": "operating EBITDA margin",
    "pbdit": "PBDIT margin (other income included)",
}


def _margin_kind(metric: str, ticker: str) -> str | None:
    m = metric.lower()
    if re.search(r"pbdit|including other income", m):
        return "pbdit"
    if "ebitda" in m:
        return "ebitda"
    if re.search(r"\bebit\b", m):
        return "ebit"
    if "operating margin" in m and PORTFOLIO.get(ticker, ("", ""))[1] == "IT services":
        return "ebit"
    return None


def _filed_quarters(c, ticker: str) -> list[dict]:
    """One row per quarter from the results filings, consolidated where both exist, oldest first."""
    rows = c.execute(
        "SELECT * FROM results WHERE ticker=? ORDER BY period_end, consolidated DESC", (ticker,)
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["period_end"], dict(r))
    return list(out.values())


def _margin_of(rows: list[dict], kind: str) -> float | None:
    """Margin over one or more quarters, summing each line first."""
    need = ("revenue", "pbt", "finance_costs", "depreciation", "other_income")
    if not rows or any(r[k] is None for r in rows for k in need):
        return None
    tot = {k: sum(r[k] for r in rows) for k in need}
    v = tot["pbt"] + tot["finance_costs"]
    if kind != "ebit":
        v += tot["depreciation"]
    if kind != "pbdit":
        v -= tot["other_income"]
    return round(100 * v / tot["revenue"], 1) if tot["revenue"] else None


def _fy_quarters(rows: list[dict], fy_end: date) -> list[dict]:
    """The quarters of the financial year ending on fy_end that have been filed so far."""
    start = date(fy_end.year - 1, 4, 1)
    return [r for r in rows if start <= date.fromisoformat(r["period_end"]) <= fy_end]


def _margin_check(c, ticker: str, p: dict, low: float, latest_q: date | None) -> dict | None:
    kind = _margin_kind(p["metric"], ticker)
    if not kind:
        return None
    rows = _filed_quarters(c, ticker)
    if not rows:
        return None
    name = _MARGIN_NAME[kind]
    due = date.fromisoformat(p["due"]) if p.get("due") else None
    if due and latest_q and due <= latest_q:
        fy = _fy_quarters(rows, due) if due.month == 3 else []
        if len(fy) == 4:
            actual, when = _margin_of(fy, kind), f"FY{due.year % 100:02d}"
        else:
            q = [r for r in rows if r["period_end"] == due.isoformat()]
            actual, when = _margin_of(q, kind), A.quarter_label(due.isoformat()) if q else ""
        if actual is None:
            return None
        return {
            "status": "delivered" if actual >= low else "missed",
            "actual": actual,
            "basis": f"{when} {name} {actual}% from the filed results{_shortfall(actual, low)}",
            "definition": kind,
        }
    last = rows[-1]
    actual = _margin_of([last], kind)
    if actual is None:
        return None
    return {
        "status": "on_track" if actual >= low else "off_track",
        "actual": actual,
        "basis": f"Latest quarter ({A.quarter_label(last['period_end'])}) {name} {actual}% from the filed results",
        "definition": kind,
    }


def _seg_key(name: str) -> str:
    """ "a) Wires & Cables" and "Wires and cables" are one segment, as are "Jewellery (refer note 4)" and
    "Jewellery"."""
    n = re.sub(r"\(.*?\)|^[a-z]\)\s*", "", name.strip().lower()).replace("&", "and")
    return " ".join(re.findall(r"[a-z]+", n))


def _segment_for(c, ticker: str, metric: str) -> tuple[str, list[dict]] | None:
    """The reported segment a promise names, with its quarters oldest first."""
    merged: dict[str, dict[str, dict]] = {}
    names: dict[str, str] = {}
    for name, qs in A.segment_history(c, ticker).items():
        k = _seg_key(name)
        names.setdefault(k, name)
        for q in qs:
            merged.setdefault(k, {})[q["quarter"]] = q
    m = metric.lower()
    for k, qs in merged.items():
        words = [w for w in k.split() if w not in ("and", "the", "segment", "business", "others", "other")]
        if words and all(re.search(rf"\b{w}\b", m) for w in words):
            order = sorted(qs.values(), key=lambda q: (int(q["quarter"][-2:]), int(q["quarter"][1])))
            return re.sub(r"\s*\(.*?\)|^[a-z]\)\s*", "", names[k]).strip(), order
    return None


def _segment_check(c, ticker: str, p: dict, low: float) -> dict | None:
    """A segment's result in the filing is before interest and tax, so it is an EBIT margin. EBITDA adds
    depreciation back and can only be higher: a segment EBIT margin at or above an EBITDA target means the target
    is met, but one below it says nothing."""
    found = _segment_for(c, ticker, p["metric"])
    if not found:
        return None
    name, qs = found
    last = qs[-1]
    if p["metric_key"] == "operating_margin":
        if not last.get("revenue") or last.get("result") is None:
            return None
        actual = round(100 * last["result"] / last["revenue"], 1)
        kind = _margin_kind(p["metric"], ticker)
        if kind != "ebit" and actual < low:
            return None
        floor = "" if kind == "ebit" else ", and EBITDA is at least that"
        return {
            "status": "on_track" if actual >= low else "off_track",
            "actual": actual,
            "basis": f"{name} segment, {last['quarter']}: result {actual}% of revenue (before interest and tax){floor}",
            "definition": "segment",
        }
    if p["metric_key"] == "revenue_growth":
        fy, qn = int(last["quarter"][-2:]), last["quarter"][:2]
        yago = next((q for q in qs if q["quarter"] == f"{qn} FY{fy - 1:02d}"), None)
        g = A.pct(last.get("revenue"), yago.get("revenue")) if yago else None
        if g is None:
            return None
        return {
            "status": "on_track" if g >= low else "off_track",
            "actual": g,
            "basis": f"{name} segment revenue, {last['quarter']} YoY {g}%",
            "definition": "segment",
        }
    return None


_REVENUE_WORDS = re.compile(r"\b(revenue|revenues|sales|top[- ]?line|turnover)\b", re.I)


def _revenue_pace(c, ticker: str, p: dict, low: float, latest_q: date | None) -> dict | None:
    """A full-year revenue target in Rs crore, against the quarters of that year filed so far."""
    due = date.fromisoformat(p["due"]) if p.get("due") else None
    if not due or due.month != 3 or not _REVENUE_WORDS.search(p["metric"]) or not _company_level(p["metric"]):
        return None
    if re.search(r"\bex[- ]|excluding|organic", p["target"] + " " + p["metric"], re.I):
        return None  # FINN cannot take the excluded part out of the filed total
    fy = _fy_quarters(_filed_quarters(c, ticker), due)
    if not fy or any(r["revenue"] is None for r in fy):
        return None
    done = sum(r["revenue"] for r in fy)
    label = f"FY{due.year % 100:02d}"
    if len(fy) == 4:
        return {
            "status": "delivered" if done >= low else "missed",
            "actual": round(done),
            "basis": f"{label} revenue Rs {_n(done)} crore from the filed results",
            "definition": "revenue",
        }
    needed = low * len(fy) / 4
    return {
        "status": "on_track" if done >= needed else "off_track",
        "actual": round(done),
        "basis": f"{label} revenue so far Rs {_n(done)} crore in {len(fy)} of 4 quarters; an even pace to "
        f"Rs {_n(low)} crore needs Rs {_n(needed)} crore. Seasonal businesses can be behind and still make it.",
        "definition": "revenue",
    }


def _numeric_check(c, ticker: str, p: dict, latest_q: date | None) -> dict | None:
    """Python verdict for promises we can measure against reported numbers. None if not measurable.

    Company totals come from the trajectory (growth) or the filed line items (margins in the definition the
    promise names, full-year revenue). A promise for one reported segment is checked against that segment's
    rows in the results filings; a product or unit that is not a reported segment cannot be checked."""
    low = p["target_low"]
    if low is None:
        return None
    if p["unit"] == "rs_crore":
        return _revenue_pace(c, ticker, p, low, latest_q)
    if p["metric_key"] not in ("operating_margin", "revenue_growth", "pat_growth") or p["unit"] != "percent":
        return None
    if not _company_level(p["metric"]):
        return _segment_check(c, ticker, p, low)
    if p["metric_key"] == "operating_margin":
        defined = _margin_check(c, ticker, p, low, latest_q)
        if defined:
            return defined
    tr = A.trajectory(c, ticker)
    due = date.fromisoformat(p["due"]) if p.get("due") else None

    if p["metric_key"] == "operating_margin":
        q = [r for r in tr["quarterly"].get("Margin %") or [] if r["value"] is not None]
        if not q:
            return None
        if due and latest_q and due <= latest_q:
            fy = [r for r in tr["annual"].get("Margin %") or [] if _period_date(r["period"]) == date(due.year, 3, 1)]
            actual = fy[0]["value"] if fy and due.month == 3 else q[-1]["value"]
            basis = f"FY margin {actual}%" if fy and due.month == 3 else f"{q[-1]['period']} margin {actual}%"
            basis += _shortfall(actual, low)
            return {"status": "delivered" if actual >= low else "missed", "actual": actual, "basis": basis}
        latest = q[-1]
        return {
            "status": "on_track" if latest["value"] >= low else "off_track",
            "actual": latest["value"],
            "basis": f"Latest quarter ({latest['period']}) operating margin {latest['value']}%, "
            "excluding other income. The company may define its margin differently.",
        }

    label = "Revenue" if p["metric_key"] == "revenue_growth" else "Net profit"
    annual = tr["annual"].get(label) or []
    if due and latest_q and due <= latest_q and due.month == 3:
        idx = next((i for i, r in enumerate(annual) if _period_date(r["period"]) == date(due.year, 3, 1)), None)
        if idx:
            g = A.pct(annual[idx]["value"], annual[idx - 1]["value"])
            if g is not None:
                return {
                    "status": "delivered" if g >= low else "missed",
                    "actual": g,
                    "basis": f"{label} growth in FY{due.year % 100:02d}: {g}%{_shortfall(g, low)}",
                }
    q = [r for r in tr["quarterly"].get(label) or [] if r["value"] is not None]
    if len(q) >= 5:
        g = A.pct(q[-1]["value"], q[-5]["value"])
        if g is not None:
            return {
                "status": "on_track" if g >= low else "off_track",
                "actual": g,
                "basis": f"{label} {q[-1]['period']} YoY {g}%",
            }
    return None


def _verdict(p: dict) -> dict:
    a = p["assessment"]
    status, judged_by = a["status"], "model"
    check = p.get("check")
    # Growth is unambiguous, so Python decides it. Margin definitions differ (Asian Paints guides on PBDIT
    # including other income, Screener's operating margin excludes it), so a margin is decided by numbers only
    # when the promise names its definition and FINN rebuilt that one from the filing; otherwise the verdict
    # rests on the verified quotes and our number is shown as context (RESEARCH R10).
    # An open-ended target can only be on or off track by the numbers; a later call that settled it (TCS said its
    # "26% to 28%" would not come in the coming quarters) is worth more than the latest quarter, so it stands.
    settled = status in ("delivered", "missed", "revised") and check and check["status"] in ("on_track", "off_track")
    if check and not settled and (p["metric_key"] != "operating_margin" or check.get("definition")):
        status, judged_by = check["status"], "numbers"
    elif p.get("revised_by") and status not in ("delivered", "missed"):
        status, judged_by = "revised", "later guidance"
    if status == "pending" and (p.get("due") or "9999") < date.today().isoformat():
        # DIXON's "20% to 25% QoQ" mobile volumes for Q2 FY27 still read "Not due yet" after Q2 was reported.
        # Phone volumes are not in the filings, so only the next call can settle it; until then it is due, open.
        status, judged_by = "awaiting", "due date"
    return {"status": status, "judged_by": judged_by}


def recheck_ledgers() -> int:
    """Re-run the Python checks on stored ledgers after new results arrive. No model calls."""
    changed = 0
    with db.session() as c:
        rows = c.execute("SELECT ticker FROM research WHERE section='ledger'").fetchall()
        for r in rows:
            t = r["ticker"]
            led = get_section(c, t, "ledger")
            if not led or led.get("status") != "ok":
                continue
            latest_q = _latest_quarter_end(c, t)
            items = []
            for it in led["items"]:
                it = {"repeated_in": [], **it, "check": _numeric_check(c, t, it, latest_q)}
                items.append({**it, **_verdict(it)})
            if items != led["items"]:
                counts: dict[str, int] = {}
                for it in items:
                    counts[it["status"]] = counts.get(it["status"], 0) + 1
                payload = {k: v for k, v in led.items() if k != "built_at"} | {"items": items, "counts": counts}
                # keep built_at: the model's reading did not change, only the numbers it is checked against
                c.execute("UPDATE research SET payload=? WHERE ticker=? AND section='ledger'", (json.dumps(payload), t))
                changed += 1
    return changed


def build_ledger(ticker: str) -> dict:
    """One reasoning call per company: the free tier allows 20 Flash requests a day (RESEARCH R9).

    Python then checks every quote, decides numeric promises from reported numbers, and spots revisions.
    """
    t0 = time.time()
    docs = load_transcripts(ticker)
    if not docs:
        return {
            "status": "no_transcripts",
            "items": [],
            "note": "No readable concall transcripts found for this company on NSE or Screener.",
        }
    with db.session() as c:
        latest_q = _latest_quarter_end(c, ticker)
        numbers = _numbers_table(c, ticker)

    texts = "\n\n".join(f"===== {d['period']} call =====\n{_paged(d)}" for d in docs)
    res: Ledger = llm.generate(
        task="ledger",
        model=llm.REASON,
        thinking="low",
        schema=Ledger,
        system=_LEDGER_SYSTEM,
        contents=f"Company: {ticker}.\n\n{numbers}\n\nTranscripts, oldest first:\n\n{texts}",
    )

    promises, unverified = [], 0
    for it in res.items:
        p = it.model_dump()
        src = _match_doc(p["source"], docs)
        page = verify_quote(p["quote"], src, p["page"]) if src else None
        if page is None:  # a promise we cannot find in the transcript is never shown
            unverified += 1
            continue
        p.update(source=src["period"], source_url=src["url"], page=page)

        a = {k: p.pop(k) for k in ("status", "note", "evidence_quote", "evidence_source", "evidence_page")}
        if a["evidence_quote"]:
            ev = _match_doc(a["evidence_source"], docs)
            is_later = ev and (_period_date(ev["period"]) or date.min) > (_period_date(src["period"]) or date.min)
            pg = verify_quote(a["evidence_quote"], ev, a["evidence_page"]) if is_later else None
            if pg is None:
                a["evidence_quote"] = None
            else:
                a.update(evidence_page=pg, evidence_source=ev["period"], evidence_url=ev["url"])
        if a["status"] in ("delivered", "missed", "revised") and not a["evidence_quote"]:
            a["status"] = "unclear"
            a["note"] = "No supporting quote from a later call could be found in the transcript."
        p["assessment"] = a
        promises.append(p)

    promises.sort(key=lambda p: _period_date(p["source"]) or date.min)
    for i, p in enumerate(promises):
        p["id"] = f"P{i + 1}"
    with db.session() as c:
        for p in promises:
            p["check"] = _numeric_check(c, ticker, p, latest_q)

    # Same measurable metric guided again later with a different target: that is a revision, decided in Python.
    for p in promises:
        p["repeated_in"] = []  # every item has the field, also those skipped below (the sheet reads it)
        if p["metric_key"] == "other":
            continue
        later = [
            q
            for q in promises
            if q["metric_key"] == p["metric_key"]
            and (_period_date(q["source"]) or date.min) > (_period_date(p["source"]) or date.min)
        ]
        changed = [
            q
            for q in later
            if (q["target_low"], q["target_high"]) != (p["target_low"], p["target_high"])
            and q["timeframe"].lower() == p["timeframe"].lower()
        ]
        if changed:
            p["revised_by"] = changed[0]["id"]
        p["repeated_in"] = [
            q["source"] for q in later if (q["target_low"], q["target_high"]) == (p["target_low"], p["target_high"])
        ]

    items = [{**p, **_verdict(p)} for p in promises]

    # Collapse repeats: keep the earliest statement of an unchanged target, note where it was repeated.
    seen = set()
    collapsed = []
    for it in items:
        key = (it["metric_key"], it["target_low"], it["target_high"], it["timeframe"].lower())
        if it["metric_key"] != "other" and key in seen:
            continue
        seen.add(key)
        collapsed.append(it)

    counts: dict[str, int] = {}
    for it in collapsed:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return {
        "status": "ok",
        "transcripts": [{"period": d["period"], "url": d["url"], "pages": len(d["pages"])} for d in docs],
        "items": collapsed,
        "counts": counts,
        "unverified_dropped": unverified,
        "build_seconds": round(time.time() - t0, 1),
        "model": llm.REASON,
    }


# ---------- bull and bear ----------


class Point(BaseModel):
    text: str = Field(description="One or two sentences, at most 35 words")
    refs: list[str] = Field(description="Ids of the facts or promises this point rests on, at least two")


class BullBear(BaseModel):
    bull: list[Point]
    bear: list[Point]


_BB_SYSTEM = """You write the bull case and the bear case for a stock, for a professional investor deciding whether to
own it. Use only the numbered facts and promises given.

Each point is an argument, not a statistic. The reader already sees every number on the page; your job is to say
what they mean together.
- A point joins at least two facts that bear on each other and says what follows for future earnings or for the
  price: a cause, a consequence or a contradiction. Cite every id it rests on.
- Restating one fact with its number is not a point.
- Say the mechanism in plain words (what drives what), then give the figures that show it.
Useful shapes: a promise against the number that tests it; a segment carrying or dragging the total; growth against
what it costs in cash, debt or margin; the P/E against the growth that has to justify it; a one-off (tax, other
income) that flatters or hides the trend.
At most 3 points each side, each at most 35 words. No adjectives like 'strong' or 'robust' unless a number backs them.
When segment facts are given, at least one point on each side rests on a segment.
Do not use anything you know about the company from elsewhere."""


def _n(v) -> str:
    """607.0 -> "607", 14.4 -> "14.4", 5515.17 -> "5,515": the model copies numbers as written."""
    if v is None:
        return "n/a"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:g}"


_GROWTH = {
    "cagr_3y": "3-year CAGR (a yearly rate)",
    "cagr_5y": "5-year CAGR (a yearly rate)",
    "last_year": "growth last year",
}


def _facts(c, ticker: str, ledger: dict | None) -> dict[str, str]:
    facts: dict[str, str] = {}
    tr = A.trajectory(c, ticker)
    for label, g in tr["growth"].items():
        for k, v in g.items():
            if v is None:
                continue
            if k == "change_pts_5y":
                facts[f"F{len(facts) + 1}"] = f"Margin change over 5 years: {_n(v)} points"
            else:
                facts[f"F{len(facts) + 1}"] = f"{label} {_GROWTH.get(k, k)}: {_n(v)}%"
    cq = A.cash_quality(c, ticker)
    if cq["cfo_to_ebitda_3y"] is not None:
        facts[f"F{len(facts) + 1}"] = (
            f"3-year cumulative operating cash flow / operating profit: {_n(cq['cfo_to_ebitda_3y'])}%"
        )
    for item, s in cq["working_capital"].items():
        if len(s) >= 2:
            name, unit = (item[:-2], "%") if item.endswith(" %") else (item, "")
            a, b = s[0], s[-1]
            facts[f"F{len(facts) + 1}"] = (
                f"{name}: {_n(a['value'])}{unit} in {a['period']}, {_n(b['value'])}{unit} in {b['period']}"
            )
    if cq["leverage"]:
        lv = cq["leverage"][-1]
        facts[f"F{len(facts) + 1}"] = f"Debt to equity in {lv['period']}: {_n(lv['debt_to_equity'])}"
    seg = A.segments(c, ticker)
    for i in (seg or {}).get("items", []):
        parts = [f"{_n(i['share_pct'])}% of segment revenue"]
        if i["margin_pct"] is not None:
            parts.append(f"segment margin {_n(i['margin_pct'])}%")
        if i["yoy"] is not None:
            parts.append(f"revenue YoY {_n(i['yoy'])}%")
        if i["share_change_pts"] is not None:
            parts.append(f"share change from a year ago {_n(i['share_change_pts'])} points")
        facts[f"F{len(facts) + 1}"] = f"{seg['quarter']} segment {i['name']}: " + ", ".join(parts)
    bk = A.bank_kpis(c, ticker)
    for text in _bank_lines(bk) if bk else []:
        facts[f"F{len(facts) + 1}"] = text
    rc = A.results_card(c, ticker)
    if rc:
        for r in rc["rows"]:
            facts[f"F{len(facts) + 1}"] = (
                f"{rc['quarter']} {r['label']}: Rs {_n(r['value'])} crore, QoQ {_n(r['qoq'])}%, YoY {_n(r['yoy'])}%"
            )
        for note in (rc.get("tax_note"), rc.get("below_ebitda")):
            if note:
                facts[f"F{len(facts) + 1}"] = f"{rc['quarter']} results note: {note}"
        if rc.get("other_income_pct_of_pbt") is not None and rc["other_income_pct_of_pbt"] >= 20:
            facts[f"F{len(facts) + 1}"] = f"{rc['quarter']} other income: {_n(rc['other_income_pct_of_pbt'])}% of PBT"
    snap = A.snapshot(c, ticker)
    ratios = (snap or {}).get("ratios") or {}
    if ratios.get("Stock P/E") is not None:
        facts[f"F{len(facts) + 1}"] = f"Price to earnings (P/E): {_n(ratios['Stock P/E'])}"
    roe_key = "ROE" if ticker in FINANCIALS else "ROCE"
    if ratios.get(roe_key) is not None:
        facts[f"F{len(facts) + 1}"] = f"{'Return on equity' if roe_key == 'ROE' else 'ROCE'}: {_n(ratios[roe_key])}%"
    if ledger:
        for it in ledger.get("items", []):
            facts[it["id"]] = (
                f"Promise ({it['source']} call): {it['metric']}, {it['target']}{_when(it)}. "
                f"Status: {_STATUS_WORDS.get(it['status'], it['status'])}"
            )
    return facts


# The model copies fact text as written; "Status: on_track" once reached a bull case verbatim.
_STATUS_WORDS = {
    "on_track": "on track",
    "off_track": "off track",
    "dropped": "not mentioned in later calls",
}


def _when(it: dict) -> str:
    """ ", by March" or ", next month"; nothing when the target already says it ("ready by March" + "by March")."""
    tf = (it.get("timeframe") or "").strip()
    if not tf or tf.lower() in it["target"].lower():
        return ""
    return f", {tf}" if re.match(r"(by|in|within|over|during|next|this)\b", tf, re.I) else f", by {tf}"


_CAGR_AS_TOTAL = re.compile(
    r"(grew|growth of|rose|increased)( by)? (\d+(?:\.\d+)?)% over (the last )?(\w+) years", re.I
)


def _yearly(text: str) -> str:
    """Flash-Lite kept writing "grew 23% over 5 years" for a 23% CAGR even when told not to (2026-10-31).
    A CAGR is a yearly rate, so the wording is fixed in code."""
    text = _CAGR_AS_TOTAL.sub(
        lambda m: f"{m.group(1)} {m.group(3)}% a year over {m.group(4) or ''}{m.group(5)} years", text
    )
    return re.sub(r"(\d) percent\b", r"\1%", text)  # one style for percentages


def build_bull_bear(ticker: str) -> dict:
    with db.session() as c:
        ledger = get_section(c, ticker, "ledger")
        facts = _facts(c, ticker, ledger)
    listing = "\n".join(f"[{k}] {v}" for k, v in facts.items())
    res: BullBear = llm.generate(
        task="bull_bear",
        model=llm.SMART,
        schema=BullBear,
        system=_BB_SYSTEM,
        contents=f"Company: {ticker}\n\n{listing}",
    )
    out = {}
    for side in ("bull", "bear"):
        pts = []
        for p in getattr(res, side):
            refs = list(dict.fromkeys(r for r in p.refs if r in facts))
            # A point on one fact restates a number already on the page; the review of 2 Nov found most did.
            if len(refs) >= 2:
                pts.append({"text": _yearly(p.text), "refs": [{"id": r, "fact": facts[r]} for r in refs]})
        out[side] = pts[:3]
    return out


# ---------- Ask ----------


class Citation(BaseModel):
    source: str = Field(description="Which call or annual report, as given in its header")
    page: int
    quote: str = Field(description="Exact words from that document, 10 to 40 words")


class Answer(BaseModel):
    covered: bool = Field(description="False if neither the figures nor the transcripts answer the question")
    answer: str = Field(description="At most 90 words")
    figures: list[str] = Field(description="Ids of the REPORTED FIGURES used, like R1")
    citations: list[Citation]


_ASK_SYSTEM = """Answer an investor's question about a company. You have up to four sources:
1. REPORTED FIGURES, numbered [R1], [R2] and so on: the company's own numbers from its results filed with the exchange
   (and its annual accounts).
2. Earnings call transcripts, where management explains the numbers.
3. ANNUAL REPORT pages: the few pages of the latest annual report that best match the question, with [page N]
   markers. Use them for what calls and results do not cover: auditors, directors and pay, subsidiaries, related
   party dealings, risks, policies, plants, employees.
4. GLOSSARY, numbered [G1], [G2] and so on: FINN's own definitions and rules. The reader may be new to investing.

For "what does this term mean" or "is this number high or low": give the GLOSSARY definition in plain words, then
this company's own figure from the REPORTED FIGURES, then FINN's rule if the glossary gives one. List the G and R
ids you used in figures. Define terms only from the GLOSSARY; if a term is not there, say FINN has no definition
for it.

For a question about numbers (revenue, profit, margins, growth, a segment, a quarter or a year):
- If the question names no period, give the latest quarter's figure from the REPORTED FIGURES.
- Answer from the REPORTED FIGURES first: the latest quarter with its change from the previous quarter and from a
  year earlier, then the last full year if it helps. List the ids you used in figures.
- Then, in a sentence or two at most, add what management said about it, naming the call by its header,
  with exact quotes. Each call discusses the quarter that ended just before it.
- "Profit" for the company means its consolidated PAT. A segment's or subsidiary's profit is never the company's
  profit: name the business whenever you use one.
- The calls and the annual report can be older than the latest results. Never present a number from them as the
  latest.
- When the question names a period (a quarter, a year), answer for that period, preferring the call that discussed
  it over the annual report. If no source covers that period, say which period your figure is for.
For anything else, answer from the transcripts or the annual report, and quote them: a number taken from a call
or the report without its quote in citations is removed before the reader sees it. A quote from the annual report
has source "Annual report" followed by its year, as in its header.
If no source answers it, set covered to false and say what they do cover.
Every sentence needs a figure id or an exact quote, but keep ids and page numbers out of the answer text; they go in
figures and citations. Copy numbers as written. Do not use outside knowledge."""


# FINN's own definitions and rules, the same as Help and "Explain the numbers" in the app. Ask may use these, and
# only these, to explain a term, so a beginner's "What does EBITDA mean?" is answered from FINN rather than refused,
# and never from the model's own knowledge. Thresholds are the scorecard's (frontend/src/scorecard.ts).
GLOSSARY = {
    "Revenue": "the money a company takes in from sales in a period.",
    "EBITDA": "operating EBITDA: profit from running the business before interest, depreciation and tax, leaving "
    "out other income. FINN computes it as PBT + finance costs + depreciation - other income.",
    "PBT": "profit before tax.",
    "PAT": "profit after tax: what is left for shareholders after all costs and tax. 'Profit' means this.",
    "Margin": "a profit line divided by revenue: of every Rs 100 of sales, how much is left as that profit.",
    "QoQ and YoY": "change against the previous quarter, and against the same quarter a year earlier; YoY avoids "
    "seasonal swings.",
    "Basis points (bps)": "hundredths of a percentage point: 100 bps is one point.",
    "Other income": "income outside the business, mostly interest on cash and gains on investments.",
    "P/E": "price to earnings: what buyers pay for every Rs 1 of the company's yearly profit.",
    "Valuation rule": "FINN divides the P/E by yearly profit growth (in %): 1x or less reads cheap for its growth, "
    "up to 2x fair, above 2x rich. It uses 3-year growth, or last year's when one year in three grew 40% or more "
    "and last year grew less than half the 3-year rate. If PAT fell 20% or more YoY in the latest quarter, growth "
    "is in doubt.",
    "ROE": "return on equity: profit in a year for every Rs 100 of shareholders' money. FINN reads 15% or more as "
    "strong for a lender, 10% as fair.",
    "ROCE": "return on capital employed: operating profit for every Rs 100 of debt and equity in the business.",
    "Debt to equity": "borrowings divided by shareholders' money. FINN reads 0.3 or less as light, up to 1 as "
    "moderate, above 1 as heavy. It says little for a lender, which borrows to lend.",
    "Cash conversion": "cash from operations as a share of operating profit; near or above 100% means profit turns "
    "into cash. FINN reads 90% or more over 3 years as strong, 70% as fair.",
    "Market cap": "the value of all the company's shares at today's price.",
    "CAGR": "compound annual growth: a yearly rate, not a total.",
    "Net interest income (NII)": "what a bank earns on loans and investments less what it pays on deposits and "
    "borrowings.",
    "NPA": "a non-performing asset is a loan unpaid for 90 days. Gross NPA counts all of them; net NPA is what is "
    "left after the money already set aside. FINN reads net NPA of 0.5% or less as clean, above 1.5% as stressed.",
    "CET1": "common equity tier 1: a bank's core capital as a share of its risk-weighted assets; higher is safer.",
    "Credit cost": "money a lender sets aside for loans that may not be repaid. FINN shows provisions as a share "
    "of pre-provision profit: 15% or less low, up to 30% moderate.",
}


def _valuation_lines(c, ticker: str) -> list[str]:
    v = A.valuation(c, ticker)
    if not v:
        return []
    out = [f"Price to earnings (P/E): {_n(v['pe'])}"]
    if v["growth"] is not None:
        out.append(f"Profit growth FINN's valuation uses ({v['basis']}): {_n(v['growth'])}%")
    if v["jump"]:
        out.append(
            f"Profit rose {_n(v['jump']['pct'])}% in the year to {v['jump']['period']}, a one-off FINN sets aside"
        )
    if v["multiple"] is not None:
        out.append(f"P/E over that growth: {_n(v['multiple'])}x, which FINN's scorecard reads as {v['verdict']}")
    else:
        out.append(f"FINN's scorecard valuation: {v['verdict']}")
    return out


def _reported(c, ticker: str) -> dict[str, dict]:
    """The company's reported numbers as short numbered facts, so Ask answers number questions from the filing
    rather than from what someone said on a call. Each fact carries where it came from."""
    out: dict[str, dict] = {}

    def add(text: str, source: str, url: str | None) -> None:
        out[f"R{len(out) + 1}"] = {"text": text, "source": source, "url": url}

    rc = A.results_card(c, ticker)
    if rc:
        basis = "consolidated" if rc["consolidated"] else "standalone"
        src = f"{rc['quarter']} results filing"
        ended = date.fromisoformat(rc["period_end"]).strftime("%-d %b %Y")
        prev_q = rc["history"][-2]["quarter"] if len(rc.get("history") or []) >= 2 else "previous quarter"
        names = {"PAT": "PAT (net profit)"}
        for r in rc["rows"]:
            if r["label"] in rc.get("suspect", []):
                continue
            name = names.get(r["label"], r["label"])
            text = f"{rc['quarter']} (quarter ended {ended}), {basis} {name}: Rs {_n(r['value'])} crore"
            if r["prev"] is not None:
                text += f"; {prev_q} Rs {_n(r['prev'])} crore, QoQ {_n(r['qoq'])}%"
            if r["year_ago"] is not None:
                text += f"; a year earlier Rs {_n(r['year_ago'])} crore, YoY {_n(r['yoy'])}%"
            add(text, src, rc["source_url"])
        for m in rc.get("margins", []):
            add(
                f"{rc['quarter']} {basis} {m['label']}: {_n(m['now'])}%, {prev_q} {_n(m['prev'])}%, a year earlier "
                f"{_n(m['year_ago'])}%",
                src,
                rc["source_url"],
            )
        if rc.get("tax_note"):
            add(f"{rc['quarter']} note: {rc['tax_note']}", src, rc["source_url"])
        if rc.get("below_ebitda"):
            add(f"{rc['quarter']} note: {rc['below_ebitda']}", src, rc["source_url"])
        if rc.get("other_income_pct_of_pbt") is not None:  # L&T's 30% was on the card but not in Ask (eval F12)
            add(
                f"{rc['quarter']} other income as a share of PBT: {_n(rc['other_income_pct_of_pbt'])}%",
                src,
                rc["source_url"],
            )
        hist = rc.get("history") or []
        for label in ("Revenue", "PAT"):
            pts = [f"{h['quarter']} {_n(h[label])}" for h in hist if h.get(label) is not None]
            if len(pts) >= 3:
                add(
                    f"{basis.capitalize()} {names.get(label, label)} by quarter, Rs crore: {', '.join(pts)}",
                    f"Results filings, last five quarters (link: {rc['quarter']})",
                    rc["source_url"],
                )
    seg = A.segments(c, ticker)
    if seg:
        # A lender's segment result is after interest (interest is its cost of goods); anyone else's is before it.
        result = "before tax" if rc and rc["is_bank"] else "before interest and tax"
        for i in seg.get("items", []):
            if not i.get("revenue"):
                continue  # "Unallocated": costs with no revenue
            parts = [f"revenue Rs {_n(i['revenue'])} crore"]
            if i.get("result") is not None:
                parts.append(f"segment result ({result}) Rs {_n(i['result'])} crore")
            if i.get("yoy") is not None:
                parts.append(f"revenue YoY {_n(i['yoy'])}%")
            add(
                f"{seg['quarter']} segment {i['name']}: " + ", ".join(parts),
                f"{seg['quarter']} results filing",
                seg["source_url"],
            )
    bk = A.bank_kpis(c, ticker)
    if bk:
        for text in _bank_lines(bk):
            add(text, f"{bk['quarters'][-1]['quarter']} standalone results filing", bk["source_url"])
    snap = A.snapshot(c, ticker) or {}
    ratios = snap.get("ratios") or {}
    src_ratios, url_ratios = "Company ratios, compiled by Screener", f"{screener.BASE}/company/{ticker}/"
    for text in _valuation_lines(c, ticker):
        add(text, src_ratios, url_ratios)
    for key, label in (("ROE", "Return on equity (ROE)"), ("ROCE", "ROCE"), ("Market Cap", "Market cap")):
        if ratios.get(key) is not None:
            unit = " crore" if key == "Market Cap" else "%"
            add(f"{label}: {'Rs ' if key == 'Market Cap' else ''}{_n(ratios[key])}{unit}", src_ratios, url_ratios)
    annual = A.trajectory(c, ticker)["annual"]
    for label in ("Revenue", "Net profit"):
        pts = [f"FY ended {a['period']} {_n(a['value'])}" for a in annual.get(label, [])[-3:]]
        if pts:
            add(
                f"{label}, full year, consolidated, Rs crore: {', '.join(pts)}",
                "Annual accounts, compiled by Screener",
                f"{screener.BASE}/company/{ticker}/consolidated/",
            )
    return out


def _bank_lines(bk: dict) -> list[str]:
    """A lender's asset quality and interest income as short facts, oldest quarter to latest in each line."""
    qs = bk["quarters"][-3:]
    out = []
    for key, label, unit in (
        ("nii", "Net interest income (interest earned less interest expended), Rs crore", ""),
        ("gnpa_pct", "Gross NPA, as filed", "%"),
        ("nnpa_pct", "Net NPA, as filed", "%"),
        ("cet1_pct", "CET1 capital ratio, as filed", "%"),
        ("nii_to_assets", "NII x 4 over total assets (FINN's ratio, not the bank's NIM)", "%"),
        ("credit_cost", "Provisions x 4 over advances (FINN's credit cost)", "%"),
    ):
        pts = [f"{q['quarter']} {_n(q[key])}{unit}" for q in qs if q[key] is not None]
        if pts:
            out.append(f"Bank standalone {label}: {', '.join(pts)}")
    last = qs[-1]
    if last["nii_yoy"] is not None:
        out.append(f"Bank standalone net interest income {last['quarter']} YoY: {_n(last['nii_yoy'])}%")
    return out


_NUM = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")
_LABELS = re.compile(r"\b(Q[1-4]|H[12]|FY|9M)\s?'?\d{0,4}|\b(19|20)\d{2}\b", re.I)


def _numbers(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in _NUM.findall(_LABELS.sub(" ", text))]


def unmatched_numbers(answer: str, sources: list[str]) -> list[str]:
    """Numbers in the answer that are in none of the sources, once rounded to the precision written: 34 matches
    33.8, and 3.33 lakh crore matches 332,861 crore, but 39.7 does not match 40.2. On 2 Nov a looser 1% check let
    DIXON's "YoY 39.7%" from an older call pass for the filed 40.2%."""
    have = [n for s in sources for n in _numbers(s)]

    def found(raw: str, lakh: bool) -> bool:
        x = float(raw.replace(",", ""))
        d = len(raw.split(".")[1]) if "." in raw else 0
        return any(abs(round(h, d) - x) < 1e-9 or (lakh and abs(round(h / 1e5, d) - x) < 1e-9) for h in have)

    out = []
    text = _LABELS.sub(" ", answer)
    for m in _NUM.finditer(text):
        raw = m.group(0)
        # Read as lakh crore only when the answer says so: ICICIBANK's "NIM was 4.18%" once passed as a Rs 4.18 lakh
        # crore figure after its quote failed, leaving a claim with no source on screen (review, 3 Nov).
        lakh = "lakh" in text[m.end() : m.end() + 12].lower()
        count = "." not in raw and float(raw.replace(",", "")) < 10  # "two calls", "3 segments"; 4.18% is not a count
        if not count and not found(raw, lakh) and raw not in out:
            out.append(raw)
    return out


def _drop_unbacked(answer: str, unmatched: list[str]) -> tuple[str, int]:
    """Remove each sentence carrying a number no source has. A wrong figure costs more trust than a shorter answer."""
    if not unmatched:
        return answer, 0
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\u201c])", answer)
    bad = re.compile(r"(?<![\d,.])(" + "|".join(re.escape(u) for u in unmatched) + r")(?![\d,]|\.\d)")
    kept = [x for x in sentences if not bad.search(_LABELS.sub(" ", x))]
    return " ".join(kept), len(sentences) - len(kept)


_REF = re.compile(r"\s*\[(?:R\d+|F\d+|G\d+|p\.|page)[^\]]*\]")  # "[R4]", "[R3, p. 3]": the model's own pointers


def _load_report_later(ticker: str) -> None:
    with _lock:
        if _jobs.get(ticker, {}).get("annual_report") == "running":
            return
        _jobs.setdefault(ticker, {})["annual_report"] = "running"

    def run() -> None:
        try:
            load_annual_report(ticker)
        finally:
            _set_job(ticker, "annual_report", "done")

    threading.Thread(target=run, daemon=True).start()


ASK_MODE = os.getenv("FINN_ASK", "pages")  # "agent": the model looks things up with tools first (eval/ask_eval.py)


def _sources(ticker: str) -> dict:
    """Everything Ask may draw on for one company: transcripts, the annual report, filed figures and the glossary."""
    docs = load_transcripts(ticker)
    # Reading a 400-page report takes longer than anyone waits for an answer: if it is not stored yet, answer
    # without it and read it in the background for the next question. The nightly job reads the portfolio's.
    ar = load_annual_report(ticker, fetch=False)
    if ar is None:
        _load_report_later(ticker)
    with db.session() as c:
        figs = _reported(c, ticker)
    gloss = {
        f"G{i + 1}": {"text": f"{k}: {v}", "source": "FINN's glossary", "url": None}
        for i, (k, v) in enumerate(GLOSSARY.items())
    }
    listing = "\n".join(f"[{k}] {v['text']}" for k, v in figs.items()) or "None"
    latest = next(
        (v["source"].removesuffix(" results filing") for v in figs.values() if "results filing" in v["source"]), None
    )
    if latest:  # "last quarter" means the latest filed one, not the one the latest call discussed
        listing += f"\nThe latest reported quarter is {latest}."
    glossary = "\n".join(f"[{k}] {v['text']}" for k, v in gloss.items())
    return {"docs": docs, "ar": ar, "figs": figs, "gloss": gloss, "listing": listing, "glossary": glossary}


# Other ways a question names a glossary term ("Is this valuation high?" rests on the valuation rule: eval G3).
_ALIASES = {
    "valuation rule": ["valuation", "valued", "expensive", "cheap", "overvalued", "undervalued"],
    "p/e": ["pe ratio", "price to earnings", "earnings multiple"],
    "npa": ["bad loans", "non-performing"],
    "debt to equity": ["debt", "leverage"],
}

_EMPTY = {
    "covered": False,
    "answer": "No results, transcripts or annual report for this company yet.",
    "figures": [],
    "citations": [],
}


def _contents(ticker: str, question: str, src: dict, texts: str, report: str) -> str:
    return (
        f"Company: {ticker}\n\nTRANSCRIPTS\n{texts or 'None'}\n\nANNUAL REPORT PAGES\n{report or 'None'}\n\n"
        f"REPORTED FIGURES\n{src['listing']}\n\nGLOSSARY\n{src['glossary']}\n\nQuestion: {question}"
    )


def _ar_section(ar: dict | None, pages: list[int]) -> str:
    if not ar or not pages:
        return ""
    return f"===== Annual report {ar['period']} =====\n" + "\n".join(
        f"[page {pg}]\n{ar['pages'][pg - 1]}" for pg in sorted(pages)
    )


def ask(ticker: str, question: str) -> dict:
    if ASK_MODE == "agent":
        return ask_agent(ticker, question)
    return ask_context(ticker, question) if ASK_MODE == "context" else ask_pages(ticker, question)


def ask_pages(ticker: str, question: str) -> dict:
    """One call, like ask_context, but only the transcript pages that best match the question: three from each
    call. All four transcripts are about 80,000 tokens, and the free tier allows 250,000 a minute, so three quick
    questions stalled on rate limits and the proxy dropped them (eval, 3 Nov; RESEARCH R16)."""
    src = _sources(ticker)
    ar_pages = report_pages(src["ar"], question) if src["ar"] else []
    if not src["docs"] and not src["figs"] and not ar_pages:
        return dict(_EMPTY)
    texts = "\n\n".join(
        f"===== {d['period']} call =====\n"
        + "\n".join(f"[page {pg}]\n{d['pages'][pg - 1]}" for pg in sorted(report_pages(d, question, k=3)))
        for d in src["docs"]
    )
    res: Answer = llm.generate(
        task="ask",
        model=llm.SMART,
        schema=Answer,
        system=_ASK_SYSTEM,
        max_wait=20,
        contents=_contents(ticker, question, src, texts, _ar_section(src["ar"], ar_pages)),
    )
    return _checked(res, src, question)


def ask_context(ticker: str, question: str) -> dict:
    """One call that reads all four transcripts, the best annual report pages, the figures and the glossary."""
    src = _sources(ticker)
    ar_pages = report_pages(src["ar"], question) if src["ar"] else []
    if not src["docs"] and not src["figs"] and not ar_pages:
        return dict(_EMPTY)
    texts = "\n\n".join(f"===== {d['period']} call =====\n{_paged(d)}" for d in src["docs"])
    res: Answer = llm.generate(
        task="ask",
        model=llm.SMART,
        schema=Answer,
        system=_ASK_SYSTEM,
        max_wait=20,
        contents=_contents(ticker, question, src, texts, _ar_section(src["ar"], ar_pages)),
    )
    return _checked(res, src, question)


def _checked(res: "Answer", src: dict, question: str) -> dict:
    """The guards every answer passes, however it was produced: quotes found word for word in their PDF, numbers
    matched to a source, and nothing shown that does not trace to one."""
    docs, ar, figs, gloss = src["docs"], src["ar"], src["figs"], src["gloss"]
    cites, dropped = [], 0
    for ct in res.citations:
        if ar and "annual" in ct.source.lower():
            d, label = ar, f"Annual report {ar['period']}"
        else:
            d = _match_doc(ct.source, docs)
            label = d["period"] if d else ""  # not "Apr 2026 call"
        pg = verify_quote(ct.quote, d, ct.page) if d else None
        if pg is None:
            # The model sometimes names a call by its quarter ("Q2 FY27 call") rather than the header's month, or
            # the wrong call. The quote is still checked word for word; only where it is looked for widens.
            for other in [x for x in reversed(docs) if x is not d] + ([ar] if ar and ar is not d else []):
                pg = verify_quote(ct.quote, other, None)
                if pg is not None:
                    d, label = other, f"Annual report {ar['period']}" if other is ar else other["period"]
                    break
        if pg is None:
            dropped += 1
            continue
        cites.append({"source": label, "page": pg, "quote": ct.quote, "url": d["url"]})
    known = {**figs, **gloss}
    ids = list(res.figures)
    # Show the definition the answer rests on even when the model did not list it: the term the question names.
    q = question.lower()
    for gid, g in gloss.items():
        term = g["text"].split(":", 1)[0].lower()
        names = [term] + re.findall(r"\(([^)]+)\)", term) + [term.split(" (")[0]] + _ALIASES.get(term, [])
        if any(re.search(rf"(?<![a-z]){re.escape(n.strip())}(?![a-z])", q) for n in names if len(n.strip()) >= 2):
            ids.append(gid)
    used = [{"id": f, **known[f]} for f in dict.fromkeys(ids) if f in known]  # an unknown id is dropped
    answer, covered = _REF.sub("", res.answer).replace(" .", "."), res.covered
    # every reported figure is a filed number, so any of them may back a number, cited or not
    sources = [f["text"] for f in known.values()] + [c["quote"] for c in cites]
    unmatched = unmatched_numbers(answer, sources)
    answer, removed = _drop_unbacked(answer, unmatched)
    unverified = covered and (not (cites or used) or not answer)  # nothing left that traces to a source
    if unverified:
        covered = False
        answer = "I could not back an answer with a reported figure or an exact quote, so I am not giving one."
    return {
        "covered": covered,
        "unverified": unverified,
        "answer": answer,
        "figures": used,
        "citations": cites,
        "unverified_dropped": dropped,
        "removed_sentences": removed,
        "unmatched_numbers": unmatched,
    }


# ---------- Ask as an agent: the model looks things up first ----------

_AGENT_SYSTEM = """You gather what is needed to answer an investor's question about one Indian listed company.
Call the tools, then reply DONE when you have enough. Do not answer the question yourself.
- get_figures: the company's filed results, growth, margins, ratios, valuation and bank figures. Use it for any
  question about numbers.
- lookup_term: FINN's own definition of a term, for "what does X mean" questions.
- search_calls: pages of the last four earnings call transcripts that match a few key words. Use it for what
  management said, guided or promised. Try a second query with other words if the first finds nothing useful.
- search_annual_report: pages of the latest annual report that match a few key words: auditors, directors,
  subsidiaries, related parties, risks, policies, plants, employees.
Use at most three tools in all."""


def _agent_tool():
    from google.genai import types

    def fn(name: str, doc: str, arg: str | None = None):
        params = (
            types.Schema(type="OBJECT", properties={arg: types.Schema(type="STRING")}, required=[arg]) if arg else None
        )
        return types.FunctionDeclaration(name=name, description=doc, parameters=params)

    return types.Tool(
        function_declarations=[
            fn("get_figures", "The company's filed figures and ratios, numbered R1, R2 and so on."),
            fn("lookup_term", "FINN's definition of a financial term.", "term"),
            fn("search_calls", "Earnings call pages matching a few key words.", "query"),
            fn("search_annual_report", "Annual report pages matching a few key words.", "query"),
        ]
    )


def _call_pages(docs: list[dict], query: str, per_call: int = 2) -> list[tuple[dict, int]]:
    """The best pages for a query in each call, newest call first, at most six in all."""
    out = []
    for d in reversed(docs):
        out += [(d, pg) for pg in report_pages(d, query, k=per_call)]
    return out[:6]


def ask_agent(ticker: str, question: str) -> dict:
    """The model plans its own lookups with tools; only what it retrieved reaches the answering call, which then
    passes the same checks as ask_context. Each tool call is returned as a trace the app can show."""
    from google.genai import types

    src = _sources(ticker)
    if not src["docs"] and not src["figs"] and not src["ar"]:
        return dict(_EMPTY)
    tool = _agent_tool()
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=f"Company: {ticker}\nQuestion: {question}")])
    ]
    trace: list[dict] = []
    call_pages: dict[str, set[int]] = {}
    ar_pages: set[int] = set()
    for _ in range(3):
        r = llm.generate(
            task="ask_plan", model=llm.SMART, contents=contents, system=_AGENT_SYSTEM, tools=[tool], max_wait=20
        )
        calls = r.function_calls or []
        if not calls or not r.candidates:
            break
        contents.append(r.candidates[0].content)
        replies = []
        for fc in calls[:3]:
            arg = dict(fc.args or {})
            text = str(arg.get("query") or arg.get("term") or "")
            if fc.name == "get_figures":
                out, found = src["listing"], f"{len(src['figs'])} figures"
            elif fc.name == "lookup_term":
                hits = [v["text"] for v in src["gloss"].values() if text.lower() in v["text"].split(":", 1)[0].lower()]
                out, found = ("\n".join(hits) or "No definition in FINN's glossary."), f"{len(hits)} definitions"
            elif fc.name == "search_calls":
                hits = _call_pages(src["docs"], text)
                for d, pg in hits:
                    call_pages.setdefault(d["period"], set()).add(pg)
                out = "\n\n".join(f"===== {d['period']} call, page {pg} =====\n{d['pages'][pg - 1]}" for d, pg in hits)
                found = ", ".join(f"{d['period']} p{pg}" for d, pg in hits) or "nothing"
            elif fc.name == "search_annual_report" and src["ar"]:
                hits = report_pages(src["ar"], text, k=4)
                ar_pages.update(hits)
                out = _ar_section(src["ar"], hits)
                found = ", ".join(f"p{pg}" for pg in hits) or "nothing"
            else:
                out, found = "Not available for this company.", "nothing"
            trace.append({"tool": fc.name, "input": text, "found": found})
            replies.append(types.Part.from_function_response(name=fc.name, response={"result": out[:60000] or "None"}))
        contents.append(types.Content(role="user", parts=replies))

    by_period = {d["period"]: d for d in src["docs"]}
    texts = "\n\n".join(
        f"===== {per} call =====\n" + "\n".join(f"[page {pg}]\n{by_period[per]['pages'][pg - 1]}" for pg in sorted(pgs))
        for per, pgs in call_pages.items()
    )
    res: Answer = llm.generate(
        task="ask",
        model=llm.SMART,
        schema=Answer,
        system=_ASK_SYSTEM,
        max_wait=20,
        contents=_contents(ticker, question, src, texts, _ar_section(src["ar"], sorted(ar_pages))),
    )
    return {**_checked(res, src, question), "trace": trace}


# ---------- analyst note on a results card ----------


class NoteLine(BaseModel):
    text: str = Field(description="One sentence, at most 30 words")
    refs: list[str] = Field(description="Ids of the facts it rests on")


class Note(BaseModel):
    sentences: list[NoteLine]


_NOTE_SYSTEM = """You write a two-sentence note on a company's quarterly results for an investor.
Sentence one: why profit moved the way it did. If an "explanation" fact is given, it is the answer: use it.
Otherwise join the facts that explain each other (revenue growth and a margin change, a segment carrying the total).
Sentence two: the one thing to watch next, from the facts: a margin falling, a one-off that will not repeat, a
segment slowing, asset quality turning. The tiles already show the headline numbers; say what they mean together.
Use only the numbered facts and cite the ids each sentence rests on. Copy numbers exactly as written in the facts.
No adjectives like 'strong' or 'robust' unless a number backs them. No advice to buy or sell."""


def _note_facts(c, ticker: str) -> tuple[dict | None, dict[str, str]]:
    rc = A.results_card(c, ticker)
    if not rc:
        return None, {}
    facts: dict[str, str] = {}

    def add(t: str) -> None:
        facts[f"N{len(facts) + 1}"] = t

    q = rc["quarter"]
    # What explains a profit swing goes first: the note's job is to say why, not to restate the tiles.
    for note in (rc.get("tax_note"), rc.get("below_ebitda")):
        if note:
            add(f"{q} explanation: {note}")
    for r in rc["rows"]:
        if r["label"] in rc.get("suspect", []) or r["value"] is None:
            continue
        add(f"{q} {r['label']}: Rs {_n(r['value'])} crore, QoQ {_n(r['qoq'])}%, YoY {_n(r['yoy'])}%")
    for m in rc.get("margins", []):
        if m["now"] is not None:
            add(f"{q} {m['label']}: {_n(m['now'])}%, change on a year earlier {_n(m['yoy_bps'])} bps")
    if rc.get("other_income_pct_of_pbt") is not None:
        add(f"{q} other income as a share of PBT: {_n(rc['other_income_pct_of_pbt'])}%")
    seg = A.segments(c, ticker)
    for i in (seg or {}).get("items", []):
        if i.get("yoy") is not None and i.get("share_pct") is not None:
            share, yoy = _n(i["share_pct"]), _n(i["yoy"])
            add(f"{seg['quarter']} segment {i['name']}: {share}% of segment revenue, revenue YoY {yoy}%")
    bk = A.bank_kpis(c, ticker)
    for text in _bank_lines(bk) if bk else []:
        add(text)
    return rc, facts


# A verb already gives the direction, so its number needs no sign: "falling by -104 bps", "rose +6.3%".
_FELL_MINUS = re.compile(
    r"\b((?:f[ae]ll(?:ing|en|s)?|drop(?:ped|ping|s)?|declin(?:ed|ing|es)|decreas(?:ed|ing|es)|slipp?(?:ed|ing|s)?|"
    r"contract(?:ed|ing|s)|ris(?:es|ing|en)|rose|grew|grow(?:ing|s)?|increas(?:ed|ing|es)|expand(?:ed|ing|s)?)"
    r"(?: by)?) [-+](\d)",
    re.I,
)


_DOWN_WORD = re.compile(r"\b(f[ae]ll|drop|declin|decreas|slip|contract|lower|down)", re.I)


def _unsigned(text: str) -> str:
    """No sign after a direction verb, next to it or later in the sentence ("falling on a year earlier by -352 bps",
    PIDILITIND, 3 Nov)."""
    text = _FELL_MINUS.sub(r"\1 \2", text)
    return re.sub(r"\bby -(\d)", r"by \1", text) if _DOWN_WORD.search(text) else text


def build_note(ticker: str) -> dict | None:
    """Two checked sentences on the latest quarter. A sentence citing no real fact, or carrying a number that is in
    none of the facts it cites, is dropped; with nothing left, there is no note."""
    with db.session() as c:
        rc, facts = _note_facts(c, ticker)
    if not rc or len(facts) < 3:
        return None
    listing = "\n".join(f"[{k}] {v}" for k, v in facts.items())
    res: Note = llm.generate(
        task="note", model=llm.SMART, schema=Note, system=_NOTE_SYSTEM, contents=f"Company: {ticker}\n\n{listing}"
    )
    kept = []
    for line in res.sentences[:2]:
        refs = [r for r in dict.fromkeys(line.refs) if r in facts]
        text = _REF.sub("", line.text).replace(" .", ".").strip()
        if refs and not unmatched_numbers(text, [facts[r] for r in refs]):
            text = _unsigned(_yearly(text))  # "fell by -71 bps" reads "fell by 71 bps"
            kept.append({"text": text, "refs": [{"id": r, "fact": facts[r]} for r in refs]})
    if not kept:
        return None
    return {"period_end": rc["period_end"], "quarter": rc["quarter"], "sentences": kept}


def note_for(c, ticker: str, period_end: str) -> dict | None:
    n = get_section(c, ticker, "note")
    return n if n and n.get("period_end") == period_end else None


def refresh_notes(tickers: list[str], force: bool = False) -> int:
    """Write a note for each company whose latest quarter has none yet. Cheap model, one call each."""
    made = 0
    for t in tickers:
        with db.session() as c:
            rc = A.results_card(c, t)
            if not rc or (note_for(c, t, rc["period_end"]) and not force):
                continue
        try:
            n = build_note(t)
        except Exception as e:  # noqa: BLE001  a missing note is fine; the card stands without it
            print(f"note: {t} failed: {e}", flush=True)
            continue
        if n:
            _save(t, "note", n)
            made += 1
    return made


# ---------- ledgers that follow new calls ----------


def ledger_changes(old: dict, new: dict) -> dict:
    """What a rebuilt ledger changed: promises whose status moved, and promises the new call added.

    A promise is matched by its quote (the same words from the same call), else by its metric and source call, so a
    re-extracted promise is not mistaken for a new one."""

    def key_q(it):
        return _norm(it["quote"])[:80]

    def key_m(it):
        return (it["source"], it["metric_key"], _norm(it["metric"]))

    before_q = {key_q(it): it for it in old.get("items", [])}
    before_m = {key_m(it): it for it in old.get("items", [])}
    known_calls = {t["period"] for t in old.get("transcripts", [])}
    moved, added = [], 0
    for it in new.get("items", []):
        prev = before_q.get(key_q(it)) or before_m.get(key_m(it))
        if prev is None:
            added += it["source"] not in known_calls
            continue
        if prev["status"] != it["status"]:
            moved.append({"metric": it["metric"], "from": prev["status"], "to": it["status"]})
    return {"moved": moved, "added": added}


_MOVED_WORD = {
    "delivered": "delivered",
    "missed": "missed",
    "on_track": "on track",
    "off_track": "off track",
    "revised": "revised",
    "dropped": "not mentioned again",
    "unclear": "unclear",
    "awaiting": "due, not settled",
    "pending": "pending",
}


def update_headline(u: dict) -> str:
    """ "Promise ledger after the Nov 2026 call: 2 now delivered, 1 revised; 3 new promises." """
    to: dict[str, int] = {}
    for m in u["moved"]:
        to[m["to"]] = to.get(m["to"], 0) + 1
    parts = [f"{n} now {_MOVED_WORD.get(k, k)}" for k, n in to.items()]
    if u["added"]:
        parts.append(f"{u['added']} new {'promise' if u['added'] == 1 else 'promises'}")
    return f"Promise ledger after the {u['call']} call: " + (", ".join(parts) if parts else "no status changed") + "."


def update_ledgers_for_new_calls(days: int = 3, limit: int = 2) -> list[dict]:
    """After a filings refresh: rebuild the ledger of any company whose new call transcript was filed in the last
    `days` and is not in its ledger yet, then record what changed for the brief and the phone. At most `limit`
    a run, and only while the reasoning model has quota (20 calls a day; RESEARCH R9)."""
    with db.session() as c:
        rows = c.execute(
            "SELECT DISTINCT ticker, an_dt FROM filings WHERE category = 'earnings_call' AND an_dt >= date('now', ?)"
            " AND (text LIKE '%ranscript%' OR nse_label LIKE '%ranscript%') ORDER BY an_dt DESC",
            (f"-{days} days",),
        ).fetchall()
        ledgers = {t: get_section(c, t, "ledger") for t in {r["ticker"] for r in rows}}
    done, seen = [], set()
    for r in rows:
        t = r["ticker"]
        old = ledgers.get(t)
        if not old or old.get("status") != "ok" or t in seen:
            continue
        seen.add(t)
        # The newest call available from any source (NSE, or Screener when NSE has only a cover letter) must be
        # newer than the newest call the ledger already read; otherwise there is nothing new to read yet.
        sync_nse_transcripts(t)
        with db.session() as c:
            calls = [d for d in document_list(c, t) if d["kind"] == "transcript"]
        newest = max((_period_date(d["period"]) or date.min for d in calls), default=date.min)
        read = max((_period_date(x["period"]) or date.min for x in old.get("transcripts", [])), default=date.min)
        if newest <= read:
            continue
        if len(done) >= limit or not (llm.has_budget(llm.REASON) or llm.has_budget(llm.REASON_FALLBACK)):
            break
        try:
            new = build_ledger(t)
        except Exception as e:  # noqa: BLE001  keep the old ledger; the next run tries again
            print(f"ledger update: {t} failed: {e}", flush=True)
            continue
        got = max((_period_date(x["period"]) or date.min for x in new.get("transcripts", [])), default=date.min)
        if new.get("status") != "ok" or got <= read:
            continue  # the new call could not be read; keep the old ledger
        period = max(new["transcripts"], key=lambda x: _period_date(x["period"]) or date.min)["period"]
        _save(t, "ledger", new)
        try:
            _save(t, "bull_bear", build_bull_bear(t))
        except Exception:  # noqa: BLE001  bull and bear can wait for the next build
            pass
        update = {"ticker": t, "call": period, "filed_at": r["an_dt"], **ledger_changes(old, new)}
        _save(t, "ledger_update", update)
        done.append(update)
    return done


# ---------- section cache and background jobs ----------


def get_section(c, ticker: str, section: str) -> dict | None:
    r = c.execute("SELECT payload, built_at FROM research WHERE ticker=? AND section=?", (ticker, section)).fetchone()
    if not r:
        return None
    return {**json.loads(r["payload"]), "built_at": r["built_at"]}


def _save(ticker: str, section: str, payload: dict) -> None:
    with db.session() as c:
        c.execute(
            "INSERT OR REPLACE INTO research(ticker, section, payload, built_at) VALUES(?,?,?,?)",
            (ticker, section, json.dumps(payload), db.now_iso()),
        )


def job_status(ticker: str) -> dict[str, str]:
    with _lock:
        return dict(_jobs.get(ticker, {}))


def _set_job(ticker: str, name: str, state: str) -> None:
    with _lock:
        _jobs.setdefault(ticker, {})[name] = state


def build_ledger_job(ticker: str, force: bool = False) -> None:
    with db.session() as c:
        if not force and get_section(c, ticker, "ledger"):
            return
    _set_job(ticker, "ledger", "running")
    try:
        _save(ticker, "ledger", build_ledger(ticker))
        _set_job(ticker, "ledger", "done")
        _set_job(ticker, "bull_bear", "running")
        _save(ticker, "bull_bear", build_bull_bear(ticker))
        _set_job(ticker, "bull_bear", "done")
    except Exception as e:
        _set_job(ticker, "ledger" if job_status(ticker).get("ledger") == "running" else "bull_bear", f"failed: {e}")
