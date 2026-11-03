"""Write eval/SPOTCHECK.md: fifteen labelled filings, weighted toward judgment calls, with FINN's current answer.

Run: uv run python -m eval.spotcheck
"""

import json
from pathlib import Path

from backend import db

HERE = Path(__file__).parent
P = {"needs_you": "Needs you", "worth_knowing": "Worth knowing", "routine": "Routine"}

# (label file, n, what the filing says, the question for the owner)
PICKS = [
    (
        "filings_labelled.json",
        29,
        "Re-appoints an independent director; same filing: Deputy MD Kaizad Bharucha ceases",
        "Should one senior exit in a mixed filing make it Needs you?",
    ),
    (
        "filings_labelled.json",
        34,
        "GST show cause notice to ICICI Bank",
        "Tax notice to a large bank: Needs you or Worth knowing?",
    ),
    ("filings_labelled.json", 39, "Postal ballot approved a performance share unit plan", "Worth knowing or Routine?"),
    (
        "holdout_labelled.json",
        4,
        "MD & CEO change at subsidiary ICICI Life",
        "Subsidiary CEO change: Worth knowing (README) or Needs you?",
    ),
    (
        "holdout_labelled.json",
        28,
        "Independent director appointed at Bajaj Auto",
        "Independent director joins: Worth knowing?",
    ),
    (
        "filings_labelled.json",
        57,
        "Tata Consumer: President and Head of India Sales appointed; a business head retires",
        "Senior staff below KMP: Worth knowing?",
    ),
    (
        "filings_labelled.json",
        31,
        "Jio Platforms (Reliance subsidiary) IPO subscription update",
        "Big subsidiary IPO: Worth knowing or Needs you?",
    ),
    (
        "filings_labelled.json",
        50,
        "Persistent QIP closed: 7.68 million shares at Rs 5,550 (about Rs 4,265 crore)",
        "Large QIP: Worth knowing or Needs you?",
    ),
    (
        "filings_labelled.json",
        49,
        "Persistent's Nagarro takeover offer ends with about 94%",
        "Completed large acquisition: Worth knowing or Needs you?",
    ),
    (
        "filings_labelled.json",
        19,
        "Press release on Persistent's Q2 results (results filed separately)",
        "Companion press release: Worth knowing?",
    ),
    (
        "filings_labelled.json",
        5,
        "Infosys delivers Syngenta's SAP transformation",
        "Client delivery, not a new order: Routine?",
    ),
    ("filings_labelled.json", 48, "Polycab: NCLAT order in an insolvency appeal against it", "Needs you?"),
    (
        "holdout_labelled.json",
        3,
        "Reliance: customs penalty of Rs 18.7 lakh",
        "Tiny penalty: Worth knowing or Routine?",
    ),
    ("filings_labelled.json", 43, "ICRA assigns AAA/Stable to Reliance (no change in standing)", "Routine?"),
    (
        "filings_labelled.json",
        26,
        "L&T wins mega orders in power transmission",
        "Order win: Worth knowing or Needs you?",
    ),
]


def main() -> None:
    sets = {f: {x["n"]: x for x in json.loads((HERE / f).read_text())["items"]} for f, *_ in PICKS}
    rows = [(sets[f][n], what, q) for f, n, what, q in PICKS]
    with db.session() as c:
        ids = [x["id"] for x, *_ in rows]
        cur = {
            r["id"]: (r["category"], r["priority"])
            for r in c.execute(
                f"SELECT id, category, priority FROM filings WHERE id IN ({','.join('?' * len(ids))})", ids
            )
        }
    lines = [
        "# Classifier spot-check",
        "",
        "Fifteen filings from the labelled sets, weighted toward judgment calls.",
        "Regenerate: `uv run python -m eval.spotcheck`.",
        "",
        "Each row gives FINN's priority, the blind label, and the question a reviewer would ask about it.",
        "",
        "| # | Company | What the filing says | FINN says | Labeller said | Question |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, (x, what, q) in enumerate(rows, 1):
        cat, pri = cur[x["id"]]
        lines.append(
            f"| {i} | {x['ticker']} | {what} | {P[pri]} ({cat.replace('_', ' ')}) | {P[x['priority']]} | {q} |"
        )
    differ = [str(i) for i, (x, _, _) in enumerate(rows, 1) if cur[x["id"]][1] != x["priority"]]
    lines += ["", f"FINN and the blind label agree on {len(rows) - len(differ)} of {len(rows)}."]
    if differ:
        lines[-1] += f" The differences ({', '.join(differ)}) are the closest calls in the set."
    lines.append("")
    (HERE / "SPOTCHECK.md").write_text("\n".join(lines))
    print("\n".join(lines[5:]))


if __name__ == "__main__":
    main()
