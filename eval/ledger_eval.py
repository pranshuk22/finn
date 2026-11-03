"""Ledger eval: score the 20 hand-read promises in ledger_labels.json. Run: uv run python -m eval.ledger_eval"""

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent


def report() -> dict:
    labels = json.loads((HERE / "ledger_labels.json").read_text())["labels"]
    n = len(labels)
    target = sum(x["target_ok"] for x in labels)
    status = Counter(x["status_label"] for x in labels)
    print(f"Ledger eval: {n} promises drawn at random")
    print(f"  target, timeframe and speaker right: {target} of {n}")
    print(f"  verdict correct: {status['correct']} of {n}", end="")
    print(f"; conservative {status['conservative']}; overclaim {status['overclaim']}")
    for x in labels:
        if x["status_label"] != "correct" or not x["target_ok"]:
            print(f"  {x['ticker']} {x['id']} {x['metric']}: {x['why']}")
    return {"n": n, "target_ok": target, **status}


if __name__ == "__main__":
    report()
