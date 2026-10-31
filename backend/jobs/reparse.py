"""Re-read every stored results filing with the current parser: segments, and quarters that a filing only gave
as six, nine or twelve months (see refresh.to_quarter). Oldest first, so a derived quarter finds the ones before it.

Run: uv run python -m backend.jobs.reparse [--dry-run]
"""

import argparse
import json
import time

from backend import db
from backend.jobs.refresh import _FIGURES, log, to_quarter
from backend.sources.nse import NSE, parse_results_ixbrl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    db.init()
    with db.session() as c:
        rows = c.execute("SELECT * FROM results WHERE source_url IS NOT NULL ORDER BY ticker, period_end").fetchall()
    nse, changed, failed = NSE(), 0, 0
    for r in rows:
        try:
            p = parse_results_ixbrl(nse.fetch_text(r["source_url"]))
        except Exception as e:  # noqa: BLE001  one bad filing should not stop the rest
            log(f"reparse: {r['ticker']} {r['period_end']} failed: {e}")
            failed += 1
            continue
        p["period_end"] = r["period_end"]
        with db.session() as c:
            q = to_quarter(c, r["ticker"], r["consolidated"], p)
            if q is None:
                log(
                    f"reparse: {r['ticker']} {r['period_end']}: {p['months']}-month figures, no quarters to derive from"
                )
                continue
            if q["derived"] or any(q.get(k) != r[k] for k in ("revenue", "pbt", "pat")):
                changed += 1
                log(
                    f"reparse: {r['ticker']} {r['period_end']} revenue {r['revenue']} -> {q.get('revenue')},"
                    f" PAT {r['pat']} -> {q.get('pat')}  {q['derived'] or ''}"
                )
            if not a.dry_run:
                c.execute(
                    "UPDATE results SET " + ", ".join(f"{k}=?" for k in _FIGURES) + ", segments=?, derived=?"
                    " WHERE ticker=? AND period_end=? AND consolidated=?",
                    (
                        *[q.get(k) for k in _FIGURES],
                        json.dumps(q["segments"]) if q.get("segments") else None,
                        q["derived"],
                        r["ticker"],
                        r["period_end"],
                        r["consolidated"],
                    ),
                )
        time.sleep(0.3)
    log(f"reparse: {len(rows)} filings read, {changed} changed, {failed} failed{' (dry run)' if a.dry_run else ''}")


if __name__ == "__main__":
    main()
