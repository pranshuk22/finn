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
from concurrent.futures import ThreadPoolExecutor
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


class Promise(BaseModel):
    metric: str = Field(description="Short name, e.g. 'Operating margin', 'Revenue growth', 'Capex'")
    metric_key: Literal["revenue_growth", "operating_margin", "pat_growth", "capex", "other"]
    target: str = Field(description="The target in plain words, e.g. '26% to 28%' or 'double-digit'")
    target_low: float | None = None
    target_high: float | None = None
    unit: Literal["percent", "rs_crore", "bps", "other"] = "other"
    timeframe: str = Field(description="As stated, e.g. 'FY27', 'next 18 to 24 months', 'long term'")
    due: str | None = Field(None, description="ISO date when the timeframe ends, or null if open-ended")
    quote: str = Field(description="Exact words copied from the transcript, 10 to 40 words")
    page: int
    speaker: str | None = None
    kind: Literal["numeric", "qualitative"]


class PromiseList(BaseModel):
    items: list[Promise]


_EXTRACT_SYSTEM = """You read one earnings call transcript of an Indian listed company and list the forward-looking
commitments that management made about the company itself.

Include: guidance on revenue or growth, margins, profit, capex, capacity, debt, order book, product launches,
and dated plans. Each must have a target or a timeframe.
Exclude: client case studies, industry or macro commentary, anything said by an analyst, past results,
and vague aspirations with neither a target nor a timeframe.

Rules:
- quote: copy 10 to 40 consecutive words exactly as written in the transcript. Do not paraphrase or fix typos.
- page: the number in the [page N] marker above the quote.
- due: resolve the timeframe to the date it ends. The Indian financial year FY27 runs from 1 April 2026 to
  31 March 2027. 'Next year' and 'next quarter' are relative to the call date given. Use null for 'long term'
  or anything open-ended.
- target_low and target_high: numbers only, in the unit given. A single number goes in both.
- Use only this transcript. Do not use anything you know about the company from elsewhere.
- At most 10 items. Prefer the most specific ones."""


def extract_promises(ticker: str, doc: dict) -> list[dict]:
    res: PromiseList = llm.generate(
        task="ledger_extract",
        model=llm.REASON,
        thinking="low",
        schema=PromiseList,
        system=_EXTRACT_SYSTEM,
        contents=f"Company: {ticker}. Call held in {doc['period']}.\n\n{_paged(doc)}",
    )
    out = []
    for p in res.items:
        real_page = verify_quote(p.quote, doc, p.page)
        d = p.model_dump()
        d.update(source=doc["period"], source_url=doc["url"], verified=real_page is not None, page=real_page or p.page)
        out.append(d)
    return out


class Assessment(BaseModel):
    id: str
    status: Literal["delivered", "missed", "revised", "dropped", "pending", "unclear"]
    note: str = Field(description="At most 20 words, plain English")
    evidence_quote: str | None = Field(None, description="Exact words from a later transcript, 10 to 40 words")
    evidence_source: str | None = Field(None, description="Which later call, as given in its header")
    evidence_page: int | None = None


class AssessmentList(BaseModel):
    items: list[Assessment]


_ASSESS_SYSTEM = """You check what happened to promises an Indian company's management made on earlier earnings calls,
using only the later call transcripts and the reported numbers given to you.

Status:
- delivered: a later call or the numbers show it happened as promised.
- missed: the timeframe has passed and it did not happen, or management said it would not.
- revised: a later call changed the target or the timeframe.
- dropped: no later call mentions it at all.
- pending: the timeframe has not ended and no later call contradicts it.
- unclear: the later calls mention it but do not settle it.

For delivered, missed and revised you must give evidence_quote: 10 to 40 words copied exactly from a later
transcript, with evidence_source and evidence_page. Do not use anything you know from outside these texts."""


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
            return {"status": "delivered" if actual >= low else "missed", "actual": actual, "basis": basis}
        latest = q[-1]
        return {
            "status": "on_track" if latest["value"] >= low else "off_track",
            "actual": latest["value"],
            "basis": f"Latest quarter ({latest['period']}) margin {latest['value']}%",
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
                    "basis": f"{label} growth in FY{due.year % 100:02d}: {g}%",
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


def build_ledger(ticker: str) -> dict:
    t0 = time.time()
    docs = load_transcripts(ticker)
    if not docs:
        return {
            "status": "no_transcripts",
            "items": [],
            "note": "No readable concall transcripts found on Screener for this company.",
        }

    with ThreadPoolExecutor(max_workers=4) as ex:
        per_doc = list(ex.map(lambda d: extract_promises(ticker, d), docs))
    promises = [p for ps in per_doc for p in ps]
    dropped_unverified = [p for p in promises if not p["verified"]]
    promises = [p for p in promises if p["verified"]]
    for i, p in enumerate(promises):
        p["id"] = f"P{i + 1}"

    with db.session() as c:
        latest_q = _latest_quarter_end(c, ticker)
        numbers = _numbers_table(c, ticker)
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
        repeated = [q for q in later if (q["target_low"], q["target_high"]) == (p["target_low"], p["target_high"])]
        if changed:
            p["revised_by"] = changed[0]["id"]
        p["repeated_in"] = [q["source"] for q in repeated]

    # Model judgment for everything that has later calls to check against.
    last_period = docs[-1]["period"]
    to_assess = [p for p in promises if p["source"] != last_period]
    assessments: dict[str, dict] = {}
    if to_assess:
        later_docs = docs[1:]
        listing = "\n".join(
            f"[{p['id']}] from {p['source']} call: {p['metric']}, target {p['target']}, "
            f'timeframe {p["timeframe"]}. Quote: "{p["quote"]}"'
            for p in to_assess
        )
        texts = "\n\n".join(f"===== {d['period']} call =====\n{_paged(d)}" for d in later_docs)
        res: AssessmentList = llm.generate(
            task="ledger_assess",
            model=llm.REASON,
            thinking="low",
            schema=AssessmentList,
            system=_ASSESS_SYSTEM,
            contents=f"Company: {ticker}.\n\n{numbers}\n\nPromises:\n{listing}\n\nLater transcripts:\n{texts}",
        )
        for a in res.items:
            a = a.model_dump()
            if a["evidence_quote"]:
                d = _match_doc(a["evidence_source"], later_docs)
                pg = verify_quote(a["evidence_quote"], d, a["evidence_page"]) if d else None
                if pg is None:
                    a["evidence_quote"] = None
                    if a["status"] in ("delivered", "missed", "revised"):
                        a["status"] = "unclear"
                        a["note"] = "The model's supporting quote could not be found in the transcript."
                else:
                    a["evidence_page"] = pg
                    a["evidence_url"] = d["url"]
            elif a["status"] in ("delivered", "missed", "revised"):
                a["status"] = "unclear"
            assessments[a["id"]] = a

    items = []
    for p in promises:
        a = assessments.get(p["id"])
        status, judged_by = "pending", "timeframe"
        if p.get("check"):  # measurable against reported numbers: Python decides, not the model
            status, judged_by = p["check"]["status"], "numbers"
        elif p.get("revised_by"):
            status, judged_by = "revised", "later guidance"
        elif a:
            status, judged_by = a["status"], "model"
        items.append({**p, "status": status, "judged_by": judged_by, "assessment": a})

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
        "unverified_dropped": len(dropped_unverified),
        "build_seconds": round(time.time() - t0, 1),
        "models": {"extract": llm.REASON, "assess": llm.REASON},
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


def _facts(c, ticker: str, ledger: dict | None) -> dict[str, str]:
    facts: dict[str, str] = {}
    tr = A.trajectory(c, ticker)
    for label, g in tr["growth"].items():
        for k, v in g.items():
            if v is not None:
                facts[f"F{len(facts) + 1}"] = f"{label} {k.replace('_', ' ')}: {v}"
    cq = A.cash_quality(c, ticker)
    if cq["cfo_to_ebitda_3y"] is not None:
        facts[f"F{len(facts) + 1}"] = (
            f"3-year cumulative operating cash flow / operating profit: {cq['cfo_to_ebitda_3y']}%"
        )
    for item, s in cq["working_capital"].items():
        if len(s) >= 2:
            facts[f"F{len(facts) + 1}"] = (
                f"{item}: {s[0]['period']} {s[0]['value']} to {s[-1]['period']} {s[-1]['value']}"
            )
    if cq["leverage"]:
        lv = cq["leverage"][-1]
        facts[f"F{len(facts) + 1}"] = f"Debt to equity {lv['period']}: {lv['debt_to_equity']}"
    rc = A.results_card(c, ticker)
    if rc:
        for r in rc["rows"]:
            facts[f"F{len(facts) + 1}"] = (
                f"{rc['quarter']} {r['label']}: {r['value']} crore, QoQ {r['qoq']}%, YoY {r['yoy']}%"
            )
    if ledger:
        for it in ledger.get("items", []):
            facts[it["id"]] = (
                f"Promise ({it['source']} call): {it['metric']} {it['target']} by {it['timeframe']}. "
                f"Status: {it['status']}"
            )
    return facts


def build_bull_bear(ticker: str) -> dict:
    with db.session() as c:
        ledger = get_section(c, ticker, "ledger")
        facts = _facts(c, ticker, ledger)
    listing = "\n".join(f"[{k}] {v}" for k, v in facts.items())
    res: BullBear = llm.generate(
        task="bull_bear",
        model=llm.REASON,
        thinking="low",
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
                pts.append({"text": p.text, "refs": [{"id": r, "fact": facts[r]} for r in refs]})
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
        model=llm.REASON,
        thinking="low",
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
