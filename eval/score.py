"""Score FINN's stored classification against the blind labels. Run: uv run python -m eval.score

Strict counts only the labelled answer. Lenient also accepts the alternatives the labeller wrote down
before seeing FINN's output (for filings that honestly fit two categories).
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from backend import db

HERE = Path(__file__).parent
RANK = {"routine": 0, "worth_knowing": 1, "needs_you": 2}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("labels", nargs="?", default="filings_labelled.json")
    a = ap.parse_args()
    labels = json.loads((HERE / a.labels).read_text())["items"]
    with db.session() as c:
        pred = {
            r["id"]: dict(r)
            for r in c.execute(
                "SELECT id, category, priority, classified_by, summary FROM filings"
                f" WHERE id IN ({','.join('?' * len(labels))})",
                [x["id"] for x in labels],
            )
        }

    rows = []
    for x in labels:
        p = pred[x["id"]]
        rows.append(
            {
                **x,
                "stage": p["classified_by"],
                "pred_category": p["category"],
                "pred_priority": p["priority"],
                "cat_strict": p["category"] == x["category"],
                "cat_lenient": p["category"] in [x["category"], *x["category_alt"]],
                "pri_strict": p["priority"] == x["priority"],
                "pri_lenient": p["priority"] in [x["priority"], *x["priority_alt"]],
                "pri_error": None
                if p["priority"] in [x["priority"], *x["priority_alt"]]
                else ("too low" if RANK[p["priority"]] < RANK[x["priority"]] else "too high"),
            }
        )

    def rate(rs, key):
        return {
            "correct": sum(r[key] for r in rs),
            "of": len(rs),
            "pct": round(100 * sum(r[key] for r in rs) / len(rs), 1),
        }

    stages = {}
    for stage in ("label", "rule", "model", "all"):
        rs = rows if stage == "all" else [r for r in rows if r["stage"] == stage]
        stages[stage] = {k: rate(rs, k) for k in ("cat_strict", "cat_lenient", "pri_strict", "pri_lenient")}
    errors = Counter(r["pri_error"] for r in rows if r["pri_error"])
    misses = [r for r in rows if not r["cat_lenient"] or not r["pri_lenient"]]

    (HERE / a.labels.replace("labelled", "results")).write_text(
        json.dumps(
            {"by_stage": stages, "priority_errors": errors, "disagreements": misses}, indent=1, ensure_ascii=False
        )
    )

    print("| Stage | n | Category (strict) | Category (lenient) | Priority (strict) | Priority (lenient) |")
    print("| --- | --- | --- | --- | --- | --- |")
    for stage, m in stages.items():
        cells = " | ".join(
            f"{m[k]['correct']}/{m[k]['of']} ({m[k]['pct']}%)"
            for k in ("cat_strict", "cat_lenient", "pri_strict", "pri_lenient")
        )
        print(f"| {stage} | {m['cat_strict']['of']} | {cells} |")
    print("\nPriority errors:", dict(errors))
    print("\nDisagreements (after alternates):")
    for r in misses:
        print(
            f"  #{r['n']} {r['ticker']} [{r['stage']}] label {r['category']}/{r['priority']}"
            f" vs FINN {r['pred_category']}/{r['pred_priority']}: {r['why']}"
        )


if __name__ == "__main__":
    main()
