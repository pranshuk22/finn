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
from backend.config import ADHOC, PORTFOLIO, USER_AGENT
from backend.sources import eod, pdf, screener
from backend.sources.nse import NSE, parse_results_ixbrl

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
        rows = cons or [r for r in rows if r.get("consolidated") in ("Standalone", "Non-Consolidated")]
        for r in rows[:quarters]:
            qe = datetime.strptime(r["qe_Date"], "%d-%b-%Y").date().isoformat()
            if (t, qe) in have or not r.get("ixbrl"):
                continue
            try:
                p = parse_results_ixbrl(nse.fetch_text(r["ixbrl"]))
            except Exception as e:
                log(f"results: {t} {qe} parse failed: {e}")
                continue
            time.sleep(0.3)
            with db.session() as c:
                c.execute(
                    "INSERT OR REPLACE INTO results(ticker, period_end, consolidated, revenue, total_income,"
                    " other_income, finance_costs, depreciation, ppop, provisions, pbt, pat, is_bank,"
                    " broadcast_at, source_url, segments) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        t,
                        p["period_end"] or qe,
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
                    ),
                )
            added += 1
    log(f"results: {added} quarters added")


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
    if "screener" in steps:
        refresh_screener(everyone)
    if {"results", "screener"} & set(steps):
        from backend.pull import recheck_ledgers

        log(f"ledgers: rechecked against new numbers, {recheck_ledgers()} changed")
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
