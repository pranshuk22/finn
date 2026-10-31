"""Fill the segment table for results stored before segments were read. Re-reads each quarter's own filing.

Run: uv run python -m backend.jobs.segments
"""

import json
import time

from backend import db
from backend.jobs.refresh import log
from backend.sources.nse import NSE, parse_results_ixbrl


def main() -> None:
    db.init()
    with db.session() as c:
        rows = c.execute(
            "SELECT ticker, period_end, consolidated, source_url FROM results"
            " WHERE segments IS NULL AND source_url IS NOT NULL ORDER BY ticker, period_end"
        ).fetchall()
    nse, filled, failed = NSE(), 0, 0
    for r in rows:
        try:
            seg = parse_results_ixbrl(nse.fetch_text(r["source_url"]))["segments"]
        except Exception as e:  # noqa: BLE001  one bad filing should not stop the rest
            log(f"segments: {r['ticker']} {r['period_end']} failed: {e}")
            failed += 1
            continue
        with db.session() as c:
            c.execute(
                "UPDATE results SET segments=? WHERE ticker=? AND period_end=? AND consolidated=?",
                (json.dumps(seg) if seg else None, r["ticker"], r["period_end"], r["consolidated"]),
            )
        filled += seg is not None
        time.sleep(0.3)
    log(f"segments: {filled} of {len(rows)} quarters filled, {failed} failed")


if __name__ == "__main__":
    main()
