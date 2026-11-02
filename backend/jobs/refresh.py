"""Pull everything FINN needs into SQLite. Safe to re-run: existing rows are skipped or upserted.

uv run python -m backend.jobs.refresh                 # everything, last 35 days of filings
uv run python -m backend.jobs.refresh --only eod
uv run python -m backend.jobs.refresh --tickers TCS,INFY --only results
"""

import argparse
import json
import time
from datetime import date, datetime, timedelta

import httpx

from backend import classify, db
from backend.analytics import _quarter_back
from backend.config import ADHOC, FINANCIALS, PORTFOLIO, USER_AGENT
from backend.sources import eod, pdf, screener
from backend.sources.nse import NSE, parse_bank_kpis, parse_results_ixbrl

STEPS = ["eod", "filings", "results", "screener"]


def _dt(s: str | None) -> str | None:
    return datetime.strptime(s, "%d-%b-%Y %H:%M:%S").isoformat() if s else None


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def refresh_eod(tickers: list[str]) -> None:
    rows = eod.download(tickers)
    with db.session() as c:
        c.executemany(
            "INSERT INTO eod(ticker, date, close, volume) VALUES(?,?,?,?) "
            "ON CONFLICT(ticker, date) DO UPDATE SET close=excluded.close, volume=excluded.volume",
            rows,
        )
        db.set_meta(c, "eod_refreshed_at", db.now_iso())
    log(f"eod: {len(rows)} rows for {len(tickers)} tickers")


def _peek(f: dict, client: httpx.Client) -> str:
    try:
        text = " ".join(pdf.pages(pdf.download(f["pdf_url"], client), max_pages=2))
        return " ".join(text.split())[:1500]
    except Exception as e:  # a missing PDF should never block classification
        log(f"  peek failed {f['ticker']} {f['id']}: {e}")
        return ""


def refresh_filings(nse: NSE, tickers: list[str], days: int) -> None:
    end = date.today()
    start = end - timedelta(days=days)
    with db.session() as c:
        known = {r["id"] for r in c.execute("SELECT id FROM filings")}
    fresh = []
    for t in tickers:
        items = nse.announcements(t, start, end)
        fresh += [f for f in items if f["id"] not in known]
    log(f"filings: {len(fresh)} new")

    with httpx.Client(timeout=60, follow_redirects=True) as pc:
        for f in fresh:
            if (
                f["pdf_url"]
                and classify.by_label(f["nse_label"]) is None
                and classify.by_rules(f["text"]) is None
                and classify.is_vague(f["text"])
            ):
                f["peek"] = _peek(f, pc)

    classify.classify(fresh)
    with db.session() as c:
        c.executemany(
            "INSERT OR REPLACE INTO filings(id, ticker, an_dt, nse_label, text, pdf_url, category, priority,"
            " summary, classified_by, enrichment) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    f["id"],
                    f["ticker"],
                    f["an_dt"],
                    f["nse_label"],
                    f["text"],
                    f["pdf_url"],
                    f["category"],
                    f["priority"],
                    f["summary"],
                    f["classified_by"],
                    None,
                )
                for f in fresh
            ],
        )
        db.set_meta(c, "filings_refreshed_at", db.now_iso())
    by = {}
    for f in fresh:
        by[f["classified_by"]] = by.get(f["classified_by"], 0) + 1
    log(f"filings: classified {by}")


_FIGURES = [
    "revenue",
    "total_income",
    "other_income",
    "finance_costs",
    "depreciation",
    "ppop",
    "provisions",
    "pbt",
    "pat",
]


def to_quarter(c, ticker: str, consolidated: int, p: dict) -> dict | None:
    """The quarter's figures from a parsed filing. A filing that covers 6, 9 or 12 months in its first column
    (COFORGE Q2 FY27 gave only six-month figures) is turned into a quarter by subtracting the stored quarters
    before it in the same year; without all of them it returns None rather than show a six-month total as a
    quarter. Checked on COFORGE: 11,698.5 - 5,527.7 = 6,170.8 crore revenue, Screener 6,171.
    """
    months = p.get("months") or 3
    if months == 3:
        return {**p, "derived": None}
    end = date.fromisoformat(p["period_end"])
    earlier = []
    for k in range(1, months // 3):
        r = c.execute(
            "SELECT * FROM results WHERE ticker=? AND period_end=? AND consolidated=? AND derived IS NULL",
            (ticker, _quarter_back(end, k), consolidated),
        ).fetchone()
        if r is None:
            return None
        earlier.append(r)
    out = {**p, "derived": f"{months} months in the filing, less the {len(earlier)} earlier quarter(s)"}
    for key in _FIGURES:
        if p.get(key) is not None and all(r[key] is not None for r in earlier):
            out[key] = round(p[key] - sum(r[key] for r in earlier), 2)
        else:
            out.pop(key, None)
    out["segments"] = None  # segment tables are not derived; the card shows the latest true quarter's instead
    return out


def _qe(r: dict) -> date:
    return datetime.strptime(r["qe_Date"], "%d-%b-%Y").date()


def refresh_results(nse: NSE, tickers: list[str], quarters: int = 5) -> None:
    """Latest `quarters` results per ticker: enough for QoQ and YoY."""
    with db.session() as c:
        have = {(r["ticker"], r["period_end"]) for r in c.execute("SELECT ticker, period_end FROM results")}
    added = 0
    for t in tickers:
        try:
            rows = nse.integrated_financials(t)
        except Exception as e:
            log(f"results: {t} list failed: {e}")
            continue
        cons = [r for r in rows if r.get("consolidated") == "Consolidated"]
        alone = [r for r in rows if r.get("consolidated") in ("Standalone", "Non-Consolidated")]
        # Consolidated when it is current. JYOTHYLAB filed consolidated results only up to Mar 2025 and standalone
        # since, so preferring any consolidated row showed an 18-month-old quarter as the latest (review, 3 Nov).
        if cons and alone and max(map(_qe, cons)) < max(map(_qe, alone)):  # NSE's list is not always in date order
            cons = []
        rows = cons or alone
        # One filing per quarter, newest first. A revised filing lists the quarter twice, and those duplicates
        # once pushed the year-ago quarter out of the last five (ASIANPAINT, GRAVITA, KAYNES: QoQ only).
        latest: dict[date, dict] = {}
        for r in rows:
            latest.setdefault(_qe(r), r)
        rows = [latest[k] for k in sorted(latest, reverse=True)[:quarters]]
        # oldest first, so a six-month filing finds the quarter before it already stored
        for r in sorted(rows, key=_qe):
            qe = datetime.strptime(r["qe_Date"], "%d-%b-%Y").date().isoformat()
            if (t, qe) in have or not r.get("ixbrl"):
                continue
            try:
                p = parse_results_ixbrl(nse.fetch_text(r["ixbrl"]))
            except Exception as e:
                log(f"results: {t} {qe} parse failed: {e}")
                continue
            time.sleep(0.3)
            p["period_end"] = p["period_end"] or qe
            with db.session() as c:
                q = to_quarter(c, t, int(bool(cons)), p)
                if q is None:
                    log(
                        f"results: {t} {qe} has only {p['months']}-month figures and no earlier quarters to derive from"
                    )
                    continue
                p = q
                c.execute(
                    "INSERT OR REPLACE INTO results(ticker, period_end, consolidated, revenue, total_income,"
                    " other_income, finance_costs, depreciation, ppop, provisions, pbt, pat, is_bank,"
                    " broadcast_at, source_url, segments, derived) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        t,
                        p["period_end"],
                        int(bool(cons)),
                        p.get("revenue"),
                        p.get("total_income"),
                        p.get("other_income"),
                        p.get("finance_costs"),
                        p.get("depreciation"),
                        p.get("ppop"),
                        p.get("provisions"),
                        p.get("pbt"),
                        p.get("pat"),
                        int(p["is_bank"]),
                        _dt(r.get("broadcast_Date") or r.get("creation_Date")),
                        r["ixbrl"],
                        json.dumps(p["segments"]) if p.get("segments") else None,
                        p["derived"],
                    ),
                )
            added += 1
    log(f"results: {added} quarters added")


_BANK_COLS = [
    "interest_earned", "interest_expended", "provisions", "gross_npa", "advances", "total_assets",
    "gnpa_pct", "nnpa_pct", "cet1_pct",
]  # fmt: skip


def refresh_bank_kpis(nse: NSE, tickers: list[str], quarters: int = 8) -> None:
    """Asset quality for banks, from their standalone filings: the consolidated ones leave NPA ratios at 0.
    Eight quarters, so the latest four each have a year-ago quarter for NII growth."""
    with db.session() as c:
        have = {(r["ticker"], r["period_end"]) for r in c.execute("SELECT ticker, period_end FROM bank_kpis")}
    added = 0
    for t in tickers:
        try:
            rows = nse.integrated_financials(t)
        except Exception as e:
            log(f"bank kpis: {t} list failed: {e}")
            continue
        rows = [r for r in rows if r.get("consolidated") == "Standalone" and "BANKING" in (r.get("ixbrl") or "")]
        for r in rows[:quarters]:
            qe = datetime.strptime(r["qe_Date"], "%d-%b-%Y").date().isoformat()
            if (t, qe) in have:
                continue
            try:
                k = parse_bank_kpis(nse.fetch_text(r["ixbrl"]))
            except Exception as e:
                log(f"bank kpis: {t} {qe} parse failed: {e}")
                continue
            time.sleep(0.3)
            with db.session() as c:
                c.execute(
                    f"INSERT OR REPLACE INTO bank_kpis(ticker, period_end, {', '.join(_BANK_COLS)}, source_url)"
                    f" VALUES(?,?,{','.join('?' * len(_BANK_COLS))},?)",
                    (t, k.get("period_end") or qe, *[k.get(col) for col in _BANK_COLS], r["ixbrl"]),
                )
            added += 1
    log(f"bank kpis: {added} quarters added")


def refresh_screener(tickers: list[str]) -> None:
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        for t in tickers:
            try:
                page = screener.fetch(t, client)
            except screener.NotFound:
                log(f"screener: {t} not found")
                continue
            except Exception as e:
                log(f"screener: {t} failed: {e}")
                continue
            store_screener(t, page)
            time.sleep(1.0)
    log(f"screener: {len(tickers)} companies")


def store_screener(ticker: str, page: dict) -> None:
    with db.session() as c:
        c.execute(
            "INSERT OR REPLACE INTO companies(ticker, name, about, ratios, statement_mode, fetched_at)"
            " VALUES(?,?,?,?,?,?)",
            (ticker, page["name"], page["about"], json.dumps(page["ratios"]), page["statement_mode"], db.now_iso()),
        )
        c.execute("DELETE FROM financials WHERE ticker=?", (ticker,))
        c.executemany(
            "INSERT OR REPLACE INTO financials(ticker, statement, period, line_item, value) VALUES(?,?,?,?,?)",
            [
                (ticker, st, r["period"], r["line_item"], r["value"])
                for st, rows in page["tables"].items()
                for r in rows
            ],
        )
        docs = [("transcript", d) for d in page["transcripts"]] + [("annual_report", d) for d in page["annual_reports"]]
        for kind, d in docs:
            c.execute(
                "INSERT INTO documents(ticker, kind, period, url) VALUES(?,?,?,?) "
                "ON CONFLICT(ticker, kind, period) DO UPDATE SET url=excluded.url",
                (ticker, kind, d["period"], d["url"]),
            )


def refresh_annual_reports(tickers: list[str]) -> None:
    """Read each company's latest annual report once, so Ask can search it without a wait."""
    from backend.pull import load_annual_report

    read = 0
    for t in tickers:
        try:
            read += load_annual_report(t) is not None
        except Exception as e:
            log(f"annual report: {t} failed: {e}")
    log(f"annual reports: {read} of {len(tickers)} stored")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=STEPS, action="append")
    ap.add_argument("--tickers", help="comma separated; default is portfolio (+ ad-hoc for results/screener)")
    ap.add_argument("--days", type=int, default=35)
    a = ap.parse_args()

    db.init()
    steps = a.only or STEPS
    portfolio = a.tickers.split(",") if a.tickers else list(PORTFOLIO)
    everyone = a.tickers.split(",") if a.tickers else list(PORTFOLIO) + ADHOC

    nse = NSE() if {"filings", "results"} & set(steps) else None
    if "eod" in steps:
        refresh_eod(portfolio)
    if "filings" in steps:
        refresh_filings(nse, portfolio, a.days)
    if "results" in steps:
        refresh_results(nse, everyone)
        refresh_bank_kpis(nse, [t for t in everyone if t in FINANCIALS])
    if "screener" in steps:
        refresh_screener(everyone)
        refresh_annual_reports(everyone)
    if {"results", "screener"} & set(steps):
        from backend.pull import recheck_ledgers

        log(f"ledgers: rechecked against new numbers, {recheck_ledgers()} changed")
    if {"filings", "eod"} & set(steps):
        from backend import push

        try:
            log(f"push: {push.notify()} new alerts sent")
        except Exception as e:  # a push service being down must not fail the refresh
            log(f"push: failed: {e}")
    with db.session() as c:
        db.set_meta(c, "refreshed_at", db.now_iso())
        log(
            "rows: "
            + json.dumps(
                {
                    t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ["eod", "filings", "results", "financials", "documents", "llm_calls"]
                }
            )
        )


if __name__ == "__main__":
    main()
