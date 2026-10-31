"""Pull side: the promise ledger, bull and bear, and Ask. Primary sources only.

Guards against made-up answers:
1. The model sees only text extracted from the company's own transcripts, or numbers computed here.
2. Every claim carries a document and page, or a fact id.
3. Every quote is checked against the source text in Python; claims whose quote is not found are dropped.
"""

import json
import re
import threading
import time
from datetime import date, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from backend import analytics as A
from backend import db, llm
from backend.config import USER_AGENT
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
    tcs.com, which also answers 403 to scripts (EVIDENCE E16).
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
            c.execute(
                "INSERT OR REPLACE INTO documents(ticker, kind, period, url, pages) VALUES(?,?,?,?,NULL)",
                (ticker, "transcript", period, f["pdf_url"]),
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
past results, and vague aspirations with neither a target nor a timeframe. At most 6 per call, the most specific.

Step 2. For each one, judge what happened using only the LATER calls and the numbers:
- delivered: a later call or the numbers show it happened as promised.
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


def _numeric_check(c, ticker: str, p: dict, latest_q: date | None) -> dict | None:
    """Python verdict for promises we can measure against reported numbers. None if not measurable."""
    if p["metric_key"] not in ("operating_margin", "revenue_growth", "pat_growth") or p["unit"] != "percent":
        return None
    low = p["target_low"]
    if low is None:
        return None
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
    # including other income, Screener's operating margin excludes it), so for margins the verdict rests on
    # the verified quotes and our number is shown only as context (EVIDENCE E20).
    if check and p["metric_key"] != "operating_margin":
        status, judged_by = check["status"], "numbers"
    elif p.get("revised_by") and status not in ("delivered", "missed"):
        status, judged_by = "revised", "later guidance"
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
                it = {**it, "check": _numeric_check(c, t, it, latest_q)}
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
    """One reasoning call per company: the free tier allows 20 Flash requests a day (EVIDENCE E19).

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
    text: str = Field(description="One sentence, at most 25 words")
    refs: list[str] = Field(description="Ids of the facts or promises this point rests on")


class BullBear(BaseModel):
    bull: list[Point]
    bear: list[Point]


_BB_SYSTEM = """You write the tightest bull case and bear case for a stock, for a professional investor.
Use only the numbered facts and promises given. Every point must cite at least one id from them.
At most 3 points each side. No adjectives like 'strong' or 'robust' unless a number backs them.
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
    rc = A.results_card(c, ticker)
    if rc:
        for r in rc["rows"]:
            facts[f"F{len(facts) + 1}"] = (
                f"{rc['quarter']} {r['label']}: Rs {_n(r['value'])} crore, QoQ {_n(r['qoq'])}%, YoY {_n(r['yoy'])}%"
            )
    if ledger:
        for it in ledger.get("items", []):
            facts[it["id"]] = (
                f"Promise ({it['source']} call): {it['metric']} {it['target']} by {it['timeframe']}. "
                f"Status: {it['status']}"
            )
    return facts


_CAGR_AS_TOTAL = re.compile(
    r"(grew|growth of|rose|increased)( by)? (\d+(?:\.\d+)?)% over (the last )?(\w+) years", re.I
)


def _yearly(text: str) -> str:
    """Flash-Lite kept writing "grew 23% over 5 years" for a 23% CAGR even when told not to (2026-10-31).
    A CAGR is a yearly rate, so the wording is fixed in code."""
    return _CAGR_AS_TOTAL.sub(
        lambda m: f"{m.group(1)} {m.group(3)}% a year over {m.group(4) or ''}{m.group(5)} years", text
    )


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
            refs = [r for r in p.refs if r in facts]
            if refs:  # a point with no valid reference is dropped
                pts.append({"text": _yearly(p.text), "refs": [{"id": r, "fact": facts[r]} for r in refs]})
        out[side] = pts[:3]
    return out


# ---------- Ask ----------


class Citation(BaseModel):
    source: str = Field(description="Which call, as given in its header")
    page: int
    quote: str = Field(description="Exact words from that transcript, 10 to 40 words")


class Answer(BaseModel):
    covered: bool = Field(description="False if the transcripts do not answer the question")
    answer: str = Field(description="At most 80 words")
    citations: list[Citation]


_ASK_SYSTEM = """Answer an investor's question about a company using only the earnings call transcripts given.
If they do not answer it, set covered to false and say what they do cover instead.
Every factual sentence needs a citation with an exact quote. Do not use outside knowledge."""


def ask(ticker: str, question: str) -> dict:
    docs = load_transcripts(ticker)
    if not docs:
        return {"covered": False, "answer": "No readable transcripts for this company.", "citations": []}
    texts = "\n\n".join(f"===== {d['period']} call =====\n{_paged(d)}" for d in docs)
    res: Answer = llm.generate(
        task="ask",
        model=llm.SMART,
        schema=Answer,
        system=_ASK_SYSTEM,
        contents=f"Company: {ticker}\n\n{texts}\n\nQuestion: {question}",
    )
    cites, dropped = [], 0
    for ct in res.citations:
        d = _match_doc(ct.source, docs)
        pg = verify_quote(ct.quote, d, ct.page) if d else None
        if pg is None:
            dropped += 1
            continue
        cites.append({"source": ct.source, "page": pg, "quote": ct.quote, "url": d["url"]})
    answer = res.answer
    covered = res.covered
    if covered and not cites:
        covered = False
        answer = "I could not back an answer with an exact quote from the transcripts, so I am not giving one."
    return {"covered": covered, "answer": answer, "citations": cites, "unverified_dropped": dropped}


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
