"""FastAPI app. Reads SQLite; only research for a ticker we have not seen does live fetching."""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import analytics as A
from backend import db, enrich, pull
from backend.config import ADHOC, ALIASES, PORTFOLIO, ROOT, resolve_ticker

IST = ZoneInfo("Asia/Kolkata")


def _no_dashes(obj):
    """Exchange filings sometimes contain em and en dashes; FINN's UI never shows them."""
    if isinstance(obj, str):
        return obj.replace("\u2014", " - ").replace("\u2013", "-")
    if isinstance(obj, list):
        return [_no_dashes(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _no_dashes(v) for k, v in obj.items()}
    return obj


class CleanJSON(JSONResponse):
    def render(self, content) -> bytes:
        return super().render(_no_dashes(content))


app = FastAPI(title="FINN", default_response_class=CleanJSON)
# The 30-day brief is 157 KB of JSON; compressed it costs a phone a fraction of that (EVIDENCE E21).
app.add_middleware(GZipMiddleware, minimum_size=1024)
db.init()

PRIORITY_ORDER = {"needs_you": 0, "worth_knowing": 1, "routine": 2}
CATEGORY_ORDER = {
    c: i
    for i, c in enumerate(
        [
            "results",
            "management_change",
            "litigation",
            "credit_rating",
            "pledging",
            "M&A",
            "fund_raise",
            "capex",
            "insider_trading",
            "dividend",
            "bonus_split",
            "press_release",
        ]
    )
}
CATEGORY_LABEL = {
    "results": "Results",
    "M&A": "M&A",
    "fund_raise": "Fund raise",
    "management_change": "Management",
    "litigation": "Litigation",
    "insider_trading": "Insider trade",
    "earnings_call": "Earnings call",
    "investor_meetings": "Investor meet",
    "credit_rating": "Credit rating",
    "dividend": "Dividend",
    "bonus_split": "Bonus or split",
    "capex": "Capex",
    "press_release": "Press release",
    "postal_ballot": "Postal ballot",
    "agm_egm": "AGM or EGM",
    "pledging": "Pledge",
    "unclassified": "Routine",
}


class AlertRules(BaseModel):
    price_pct: float = Field(3.0, ge=0.5, le=20)
    vol_mult: float = Field(2.0, ge=1.0, le=10)
    categories: list[str] = ["results", "management_change", "litigation", "credit_rating", "pledging", "M&A"]


def _rules(c) -> AlertRules:
    return AlertRules(**db.get_meta(c, "alert_rules", {}))


def _now() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def _name(ticker: str) -> str:
    return PORTFOLIO[ticker][0] if ticker in PORTFOLIO else ticker


@app.get("/api/brief")
def brief(hours: int = Query(24, ge=1, le=24 * 90)):
    since = _now() - timedelta(hours=hours)
    with db.session() as c:
        rules = _rules(c)
        rows = c.execute("SELECT * FROM filings WHERE an_dt >= ? ORDER BY an_dt DESC", (since.isoformat(),)).fetchall()

        groups: dict[tuple[str, str], list] = {}
        routine = []
        for r in rows:
            if r["priority"] == "routine":
                routine.append(r)
            else:
                groups.setdefault((r["ticker"], r["category"]), []).append(r)

        cards = []
        for (ticker, cat), fs in groups.items():
            best = min(fs, key=lambda f: PRIORITY_ORDER[f["priority"]])
            card = {
                "id": f"{ticker}:{cat}:{fs[0]['id']}",
                "ticker": ticker,
                "name": _name(ticker),
                "category": cat,
                "category_label": CATEGORY_LABEL.get(cat, cat),
                "priority": best["priority"],
                "latest_at": fs[0]["an_dt"],
                "headline": best["summary"],
                "alert": cat in rules.categories,
                "filings": [
                    {
                        "id": f["id"],
                        "at": f["an_dt"],
                        "summary": f["summary"],
                        "pdf_url": f["pdf_url"],
                        "label": f["nse_label"],
                        "classified_by": f["classified_by"],
                    }
                    for f in fs
                ],
                "results": None,
                "people": None,
                "scale": None,
            }
            if cat == "results":
                rc = A.results_card(c, ticker)
                if rc and rc["broadcast_at"] and rc["broadcast_at"] >= (since - timedelta(days=2)).isoformat():
                    card["results"] = rc
                    card["headline"] = f"{rc['quarter']}: {A.results_headline(rc)}"
            people: dict[tuple[str, str], dict] = {}
            amount = None
            for f in fs:
                if not f["enrichment"]:
                    continue
                e = json.loads(f["enrichment"])
                for p in e.get("people") or []:
                    people.setdefault((p["name"].lower().replace(".", ""), p["change"]), p)
                amount = amount or e.get("amount_rs_crore")
            if people:
                card["people"] = list(people.values())
                own = [p for p in card["people"] if not p.get("entity") and p["change"] in ("joining", "leaving")]
                # a board meeting can file results and an appointment together; the results line stays the headline
                if not card["results"]:
                    card["headline"] = enrich.people_line(own or card["people"]) or card["headline"]
            if amount:
                card["scale"] = A.scale(c, ticker, amount)
            cards.append(card)
        # newest first within the same priority and category (two stable sorts)
        cards.sort(key=lambda k: k["latest_at"], reverse=True)
        cards.sort(key=lambda k: (PRIORITY_ORDER[k["priority"]], CATEGORY_ORDER.get(k["category"], 99)))

        trading_days = max(1, round(hours / 24))
        moves = A.eod_scan(c, list(PORTFOLIO), rules.price_pct, rules.vol_mult, days=trading_days)
        for m in moves:
            m["name"] = _name(m["ticker"])
            m["spark"] = A.sparkline(c, m["ticker"], 30)

        routine_by_cat: dict[str, int] = {}
        for r in routine:
            routine_by_cat[CATEGORY_LABEL.get(r["category"], r["category"])] = (
                routine_by_cat.get(CATEGORY_LABEL.get(r["category"], r["category"]), 0) + 1
            )

        return {
            "window_hours": hours,
            "since": since.isoformat(),
            "needs_you": [k for k in cards if k["priority"] == "needs_you"],
            "worth_knowing": [k for k in cards if k["priority"] == "worth_knowing"],
            "moves": moves,
            "routine": {
                "count": len(routine),
                "by_category": routine_by_cat,
                "items": [
                    {
                        "id": r["id"],
                        "ticker": r["ticker"],
                        "at": r["an_dt"],
                        "summary": r["summary"],
                        "category_label": CATEGORY_LABEL.get(r["category"], r["category"]),
                        "pdf_url": r["pdf_url"],
                    }
                    for r in routine
                ],
            },
            "total_filings": len(rows),
            "freshness": _freshness(c),
        }


@app.get("/api/alerts/rules")
def get_rules():
    with db.session() as c:
        return _rules(c)


@app.put("/api/alerts/rules")
def put_rules(rules: AlertRules):
    with db.session() as c:
        db.set_meta(c, "alert_rules", rules.model_dump())
    return rules


@app.get("/api/alerts/scan")
def scan(
    price_pct: float = Query(3.0, ge=0.5, le=20),
    vol_mult: float = Query(2.0, ge=1, le=10),
    days: int = Query(60, ge=1, le=90),
):
    """Replay the thresholds over stored EOD history: what would have fired."""
    with db.session() as c:
        hits = A.eod_scan(c, list(PORTFOLIO), price_pct, vol_mult, days)
        n_days = c.execute("SELECT COUNT(DISTINCT date) FROM eod").fetchone()[0]
    per_ticker: dict[str, int] = {}
    for h in hits:
        per_ticker[h["ticker"]] = per_ticker.get(h["ticker"], 0) + 1
    return {"count": len(hits), "days": min(days, n_days), "per_ticker": per_ticker, "hits": hits[:50]}


@app.get("/api/companies")
def companies():
    with db.session() as c:
        known = {r["ticker"]: r["name"] for r in c.execute("SELECT ticker, name FROM companies")}
    return {
        "portfolio": [{"ticker": t, "name": v[0], "sector": v[1], "size": v[2]} for t, v in PORTFOLIO.items()],
        "adhoc": [{"ticker": t, "name": known.get(t, t)} for t in ADHOC],
        "aliases": ALIASES,
    }


@app.get("/api/research/{raw}")
def research(raw: str):
    ticker = resolve_ticker(raw)
    try:
        pull.ensure_company(ticker)
    except pull.UnknownTicker:
        raise HTTPException(404, f"No Screener page for {ticker}. Check the NSE symbol.") from None
    with db.session() as c:
        snap = A.snapshot(c, ticker)
        if snap is None:
            raise HTTPException(404, f"No data for {ticker}")
        return {
            "ticker": ticker,
            "resolved_from": raw.upper() if raw.upper() != ticker else None,
            "in_portfolio": ticker in PORTFOLIO,
            "snapshot": snap,
            "results": A.results_card(c, ticker),
            "trajectory": A.trajectory(c, ticker),
            "cash_quality": A.cash_quality(c, ticker),
            "documents": pull.document_list(c, ticker),
            "ledger": pull.get_section(c, ticker, "ledger"),
            "bull_bear": pull.get_section(c, ticker, "bull_bear"),
            "jobs": pull.job_status(ticker),
        }


_jobs_lock = threading.Lock()


@app.post("/api/research/{raw}/ledger")
def build_ledger(raw: str, force: bool = False):
    ticker = resolve_ticker(raw)
    with _jobs_lock:
        if pull.job_status(ticker).get("ledger") == "running":
            return {"status": "running"}
        threading.Thread(target=pull.build_ledger_job, args=(ticker, force), daemon=True).start()
    return {"status": "started"}


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/research/{raw}/ask")
def ask(raw: str, q: Question):
    return pull.ask(resolve_ticker(raw), q.question)


@app.get("/api/meta")
def meta():
    with db.session() as c:
        calls = c.execute(
            "SELECT model, COUNT(*) n, SUM(tokens_in) i, SUM(tokens_out) o, SUM(tokens_thinking) th,"
            " SUM(tokens_cached) ca, AVG(latency_ms) lat, SUM(1 - ok) failed FROM llm_calls GROUP BY model"
        ).fetchall()
        by_task = c.execute("SELECT task, COUNT(*) n FROM llm_calls GROUP BY task").fetchall()
        return {
            "freshness": _freshness(c),
            "llm": [dict(r) for r in calls],
            "llm_by_task": {r["task"]: r["n"] for r in by_task},
            "classified_by": {r[0]: r[1] for r in c.execute("SELECT classified_by, COUNT(*) FROM filings GROUP BY 1")},
        }


def _freshness(c) -> dict:
    last_eod = c.execute("SELECT MAX(date) FROM eod").fetchone()[0]
    return {
        "refreshed_at": db.get_meta(c, "refreshed_at"),
        "filings_refreshed_at": db.get_meta(c, "filings_refreshed_at"),
        "last_eod_date": last_eod,
    }


# ---------- production: serve the built frontend ----------

DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and Path(f).resolve().is_relative_to(DIST.resolve()):
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
