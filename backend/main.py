"""FastAPI app. Reads SQLite; only research for a ticker we have not seen does live fetching."""

import json
import os
import re
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import analytics as A
from backend import db, enrich, llm, pull, push
from backend.config import ADHOC, ALIASES, PORTFOLIO, ROOT, resolve_ticker
from backend.sources.nse import NSE

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
# The 30-day brief is 157 KB of JSON; compressed it costs a phone a fraction of that (RESEARCH E21).
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


AMOUNT_CATEGORIES = {"M&A", "fund_raise", "capex", "litigation", "credit_rating", "press_release"}


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


def _level(role: str) -> str:
    """top: CEO, CFO, MD, executive directors, chair, KMP. board: other directors. staff: senior management."""
    if enrich.is_senior(role):
        return "top"
    return "board" if "director" in (role or "").lower() else "staff"


def _price_story(c, ticker: str) -> dict | None:
    """Daily closes we hold, with the filings that mattered placed on the session they could first move the price.

    A filing after the 15:30 IST close lands on the next session, the same rule as `analytics.reaction`.
    Routine filings are left off: the chart should show what an investor would have wanted to know.
    """
    rows = c.execute("SELECT date, close FROM eod WHERE ticker=? ORDER BY date", (ticker,)).fetchall()
    if len(rows) < 20:
        return None
    dates = [r["date"] for r in rows]
    events: dict[str, list[dict]] = {}
    for f in c.execute(
        "SELECT an_dt, category, priority, summary FROM filings WHERE ticker=? AND priority != 'routine'"
        " AND category IS NOT NULL AND an_dt >= ? ORDER BY an_dt",
        (ticker, dates[0]),
    ):
        day, at = f["an_dt"][:10], f["an_dt"][11:16]
        session = next((d for d in dates if d > day or (d == day and at < "15:30")), None)
        if session is None:
            continue
        events.setdefault(session, []).append(
            {
                "category_label": CATEGORY_LABEL.get(f["category"], f["category"]),
                "priority": f["priority"],
                "summary": f["summary"],
                "at": f["an_dt"],
            }
        )
    return {
        "series": [{"date": r["date"], "close": round(r["close"], 2)} for r in rows],
        "events": [{"date": d, "filings": fs} for d, fs in sorted(events.items())],
    }


def _filed_before(c, ticker: str, day: str) -> list[dict]:
    """What the company filed between the previous close and this session's close: the likely explanation
    for a price or volume move, or, if empty, a sign that nothing on record explains it. One entry per
    category, most important first: Trent's results must not hide behind four later management filings."""
    d = date.fromisoformat(day)
    prev = d - timedelta(days=3 if d.weekday() == 0 else 1)
    rows = c.execute(
        "SELECT category, summary, priority, an_dt FROM filings WHERE ticker=? AND an_dt >= ? AND an_dt < ?"
        " AND priority != 'routine'",
        (ticker, f"{prev.isoformat()}T15:30:00", f"{day}T15:30:00"),
    ).fetchall()
    rows = sorted(rows, key=lambda r: (PRIORITY_ORDER[r["priority"]], CATEGORY_ORDER.get(r["category"], 99)))
    out, seen = [], set()
    for r in rows:
        if r["category"] not in seen:
            seen.add(r["category"])
            label = CATEGORY_LABEL.get(r["category"], r["category"])
            out.append({"category_label": label, "summary": r["summary"], "at": r["an_dt"]})
    return out[:3]


def _people_headline(people: list[dict]) -> str | None:
    """Lead with who matters most: a senior change at the company, then a senior change at a subsidiary (named),
    then anyone joining or leaving. ICICI Bank's filing on ICICI Life's new CEO otherwise led with a staff exit."""
    moves = [p for p in people if p["change"] in ("joining", "leaving")]
    own = [p for p in moves if not p.get("entity")]
    senior_own = [p for p in own if enrich.is_senior(p["role"])]
    senior_sub = [p for p in moves if p.get("entity") and enrich.is_senior(p["role"])]
    if senior_own:
        return enrich.people_line(senior_own)
    if senior_sub:
        return f"{senior_sub[0]['entity']}: {enrich.people_line(senior_sub)}"
    return enrich.people_line(own or people)


_LEVEL_WEIGHT = {"top": 3, "board": 2, "staff": 1}


def _weight(card: dict) -> float:
    """How much a card matters next to others of its kind. Results: the size of the year-on-year profit change
    (PBT when tax distorts PAT). People: the most senior person. Deals and legal: size against market cap."""
    rc = card["results"]
    if rc and not rc["suspect"]:
        line = next((r for r in rc["rows"] if r["label"] == ("PBT" if rc["tax_note"] else "PAT")), None)
        return abs(line["yoy"]) if line and line["yoy"] is not None else 0
    if card["people"]:
        return max(_LEVEL_WEIGHT.get(p["level"], 0) + (0.5 if p["change"] == "leaving" else 0) for p in card["people"])
    if card["scale"] and card["scale"].get("pct_of_market_cap") is not None:
        return card["scale"]["pct_of_market_cap"]
    return 0


_HONORIFIC = re.compile(r"^(mr|mrs|ms|dr|shri|smt|prof)\s+")


def _immaterial(scale: dict) -> bool:
    """Under 0.1% of both revenue and market cap: worth knowing at most, never an alert."""
    rev, cap = scale.get("pct_of_revenue"), scale.get("pct_of_market_cap")
    return all(x is not None and x < 0.1 for x in (rev, cap)) or (rev is None and cap is not None and cap < 0.1)


def _window(c, hours: int) -> tuple[datetime, int]:
    """Where a brief window starts, and how many trading sessions of price moves it covers.

    Filings and prices share one rule: the window holds the last N sessions (N from the calendar span, weekends
    excluded) and every filing since the close of the session before them, so the news behind each move shown is
    in the same brief. On Monday 2 Nov, "24 hours" started Sunday night: DIXON's +12% and RELIANCE's +11.6% were
    listed, but the results that moved them, filed Friday evening, were not. It never starts later than `hours` ago.
    """
    sessions = max(1, round(hours / 24 * 5 / 7))
    dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM eod ORDER BY date DESC LIMIT ?", (sessions + 1,))]
    since = _now() - timedelta(hours=hours)
    if len(dates) > sessions:
        close = datetime.combine(date.fromisoformat(dates[sessions]), datetime.min.time()).replace(hour=15, minute=30)
        if close >= since - timedelta(days=4):  # a long weekend at most; stale prices must not stretch the window
            since = min(since, close)
    return since, sessions


@app.get("/api/brief")
def brief(hours: int = Query(24, ge=1, le=24 * 90)):
    with db.session() as c:
        since, sessions = _window(c, hours)
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
                "first_at": fs[-1]["an_dt"],
                "reaction": None,
                "ledger": None,
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
                    # "Mr. Anup Bagchi" in one filing and "Anup Bagchi" in the next are one person
                    key = _HONORIFIC.sub("", p["name"].lower().replace(".", "")).strip()
                    people.setdefault((key, p["change"]), p)
                amount = amount or e.get("amount_rs_crore")
            if people:
                for p in people.values():
                    p["level"] = _level(p["role"])
                # the CEO before a group head: HDFCBANK's card once opened with a business-banking head leaving
                rank = {"top": 0, "board": 1}
                card["people"] = sorted(people.values(), key=lambda p: rank.get(p["level"], 2))
                # a board meeting can file results and an appointment together; the results line stays the headline
                if not card["results"]:
                    card["headline"] = _people_headline(card["people"]) or card["headline"]
            # Only where a size means something; an appointment filing once yielded "Rs 1,143 crore" from a profile.
            if amount and cat in AMOUNT_CATEGORIES:
                card["scale"] = A.scale(c, ticker, amount)
                if _immaterial(card["scale"]):
                    card["alert"] = False  # RELIANCE's Rs 18.7 lakh customs penalty carried an Alert tag
            if ticker in PORTFOLIO:  # prices are kept for the portfolio only
                at = card["results"]["broadcast_at"] if card["results"] else best["an_dt"]
                card["reaction"] = A.reaction(c, ticker, at)
            led = pull.get_section(c, ticker, "ledger")
            if led and led.get("status") == "ok":
                card["ledger"] = {"counts": led["counts"], "promises": len(led["items"])}
            cards.append(card)
        # Within a priority and category, the card that matters most first; ties newest first (stable sorts).
        cards.sort(key=lambda k: k["latest_at"], reverse=True)
        cards.sort(key=lambda k: (PRIORITY_ORDER[k["priority"]], CATEGORY_ORDER.get(k["category"], 99), -_weight(k)))

        moves = A.eod_scan(c, list(PORTFOLIO), rules.price_pct, rules.vol_mult, days=sessions)
        for m in moves:
            m["name"] = _name(m["ticker"])
            m["spark"] = A.sparkline(c, m["ticker"], 30)
            m["filed"] = _filed_before(c, m["ticker"], m["date"])

        # NSE sometimes publishes the same filing several times in the same second (BAJAJ-AUTO's investor meet
        # on 29 Oct came three times, one per attachment). Show it once, with how many copies there were.
        copies: dict[tuple, list] = {}
        for r in routine:
            copies.setdefault((r["ticker"], r["an_dt"], r["text"]), []).append(r)

        routine_by_cat: dict[str, int] = {}
        for r in routine:
            routine_by_cat[CATEGORY_LABEL.get(r["category"], r["category"])] = (
                routine_by_cat.get(CATEGORY_LABEL.get(r["category"], r["category"]), 0) + 1
            )

        return {
            "window_hours": hours,
            "since": since.isoformat(),
            "sessions": sessions,
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
                        "copies": len(same),
                    }
                    for same in copies.values()
                    for r in same[:1]
                ],
            },
            "total_filings": len(rows),
            "portfolio_day": A.portfolio_day(c, list(PORTFOLIO)),
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


def _glance(c, ticker: str) -> dict:
    """What a watchlist row shows: last close and the day's move with a 30-day line (portfolio only, prices are
    kept for it), and the latest quarter's headline growth."""
    out: dict = {"close": None, "move_pct": None, "date": None, "spark": [], "results": None}
    rows = c.execute("SELECT date, close FROM eod WHERE ticker=? ORDER BY date DESC LIMIT 2", (ticker,)).fetchall()
    if len(rows) == 2 and rows[1]["close"]:
        out.update(
            close=round(rows[0]["close"], 2),
            date=rows[0]["date"],
            move_pct=round(100 * (rows[0]["close"] / rows[1]["close"] - 1), 2),
            spark=A.sparkline(c, ticker, 30),
        )
    rc = A.results_card(c, ticker)
    if rc and not rc["suspect"]:
        profit = "PBT" if rc["tax_note"] else "PAT"
        key = "yoy" if rc["has_year_ago"] else "qoq"
        by = {r["label"]: r[key] for r in rc["rows"]}
        out["results"] = {
            "quarter": rc["quarter"],
            "basis": key.upper(),
            "revenue": by.get("Revenue"),
            "profit_label": profit,
            "profit": by.get(profit),
        }
    return out


@app.get("/api/companies")
def companies():
    with db.session() as c:
        known = {r["ticker"]: r["name"] for r in c.execute("SELECT ticker, name FROM companies")}
        return {
            "portfolio": [
                {"ticker": t, "name": v[0], "sector": v[1], "size": v[2], **_glance(c, t)} for t, v in PORTFOLIO.items()
            ],
            "adhoc": [{"ticker": t, "name": known.get(t, t), **_glance(c, t)} for t in ADHOC],
            "aliases": ALIASES,
        }


def _equities() -> list[dict]:
    """NSE's list of listed equities, cached for a week in the meta table."""
    with db.session() as c:
        cached = db.get_meta(c, "nse_equity_list")
    if cached and cached["at"] > (datetime.now(UTC) - timedelta(days=7)).isoformat():
        return cached["rows"]
    try:
        rows = NSE().equity_list()
    except Exception:  # noqa: BLE001  an old list beats no search
        return cached["rows"] if cached else []
    with db.session() as c:
        db.set_meta(c, "nse_equity_list", {"at": db.now_iso(), "rows": rows})
    return rows


@app.get("/api/search")
def search(q: str):
    """Symbol or company name to NSE symbols. Exact symbol first, then symbol prefix, then a name word that
    starts with the query, then a name that contains it. "bharat electronics" finds BEL."""
    term = q.strip().upper()
    if len(term) < 2:
        return {"matches": []}
    ranked = []
    for e in _equities():
        sym, name = e["ticker"], e["name"].upper()
        if sym == term or resolve_ticker(term) == sym:
            rank = 0
        elif sym.startswith(term):
            rank = 1
        elif name.startswith(term) or f" {term}" in f" {name}":
            rank = 2
        elif term in name:
            rank = 3
        else:
            continue
        ranked.append((rank, len(name), e))
    return {"matches": [e for _, _, e in sorted(ranked, key=lambda x: x[:2])[:8]]}


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
            "price": _price_story(c, ticker),
            "segments": A.segments(c, ticker),
            "cash_quality": A.cash_quality(c, ticker),
            "balance_sheet": A.balance_sheet(c, ticker),
            "bank_kpis": A.bank_kpis(c, ticker),
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


@app.get("/api/research/{raw}/jobs")
def jobs(raw: str):
    """Cheap poll for the ledger build; the full research payload is only refetched when a job finishes."""
    ticker = resolve_ticker(raw)
    with db.session() as c:
        has_ledger = pull.get_section(c, ticker, "ledger") is not None
    b = llm.budget()
    flash_left = sum(b[m]["per_day"] - b[m]["used_today"] for m in (llm.REASON, llm.REASON_FALLBACK))
    return {"jobs": pull.job_status(ticker), "has_ledger": has_ledger, "flash_left_today": max(0, flash_left)}


@app.exception_handler(llm.BudgetExhausted)
def budget_exhausted(_request, _exc):
    return CleanJSON(
        status_code=503,
        content={
            "detail": "The model's free daily quota is used up. It resets at 12:30 IST; stored ledgers still work."
        },
    )


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/research/{raw}/ask")
def ask(raw: str, q: Question):
    return pull.ask(resolve_ticker(raw), q.question)


class PushSub(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: dict[str, str]


@app.get("/api/push/key")
def push_key():
    return {"key": push.public_key()}


@app.post("/api/push/subscribe")
def push_subscribe(sub: PushSub):
    push.subscribe(sub.model_dump())
    return {"ok": True}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(sub: PushSub):
    push.unsubscribe(sub.endpoint)
    return {"ok": True}


@app.get("/api/health")
def health():
    # The watchdog (deploy/finn-watchdog.service) restarts the API when this stops answering.
    with db.session() as c:
        c.execute("SELECT 1").fetchone()
    return {"ok": True}


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
            "budget": llm.budget(),
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
APP_URL = os.getenv("FINN_APP_URL")  # where the app is served when this server only runs the API

if APP_URL and not DIST.exists():

    @app.get("/")
    def to_app():
        return RedirectResponse(APP_URL)

elif DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and Path(f).resolve().is_relative_to(DIST.resolve()):
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
