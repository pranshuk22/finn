"""Re-apply the exchange-label map, text rules and priority rules to stored filings after they change.

Deterministic by default. A filing the rules cannot place keeps the model's earlier category, except one whose
exchange label is now treated as ambiguous: with --model it goes through the same PDF peek and Flash-Lite path as
a new filing. Summaries from the filing reader are kept, and a management change keeps the priority decided from
the people in its PDF.
Run: uv run python -m backend.jobs.reclassify [--dry-run] [--model]
"""

import argparse
import json

import httpx

from backend import db
from backend.classify import by_label, by_rules, classify, priority
from backend.enrich import management_priority
from backend.jobs.refresh import _peek


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", action="store_true", help="also send filings with a now-ambiguous label to Flash-Lite")
    a = ap.parse_args()

    changes, for_model = [], []
    with db.session() as c:
        for f in c.execute("SELECT * FROM filings").fetchall():
            cat, how = by_label(f["nse_label"]), "label"
            if cat is None:
                cat, how = by_rules(f["text"]), "rule"
            if cat is None:
                if f["classified_by"] == "label":  # its label is now treated as ambiguous: the model decides
                    for_model.append(dict(f))
                    continue
                if f["category"] != "management_change":
                    continue
                cat, how = f["category"], f["classified_by"]  # the model placed it; only its priority is re-derived
            pri = priority(cat, f["text"], f["nse_label"])
            people = (json.loads(f["enrichment"]) if f["enrichment"] else {}).get("people")
            if cat == "management_change":
                # Decided by who joins or leaves, read from the PDF. The exchange summary ("change in
                # Management") cannot tell a CEO exit from a re-appointment, so without people keep what is stored.
                pri = management_priority(people) if people else f["priority"]
            if (cat, how, pri) != (f["category"], f["classified_by"], f["priority"]):
                changes.append((f, cat, how, pri))
                if not a.dry_run:
                    c.execute(
                        "UPDATE filings SET category=?, classified_by=?, priority=? WHERE id=?",
                        (cat, how, pri, f["id"]),
                    )

    if for_model and a.model and not a.dry_run:
        # Same path as a new filing: peek into the PDF, then Flash-Lite in one batch.
        with httpx.Client(timeout=60, follow_redirects=True) as pc:
            for f in for_model:
                f["peek"] = _peek(f, pc) if f["pdf_url"] else ""
        classify(for_model)
        with db.session() as c:
            for f in for_model:
                keep_summary = bool(f["enrichment"])
                c.execute(
                    "UPDATE filings SET category=?, classified_by=?, priority=?"
                    + ("" if keep_summary else ", summary=?")
                    + " WHERE id=?",
                    (
                        f["category"],
                        f["classified_by"],
                        f["priority"],
                        *([] if keep_summary else [f["summary"]]),
                        f["id"],
                    ),
                )
                result = f"{f['category']}/{f['priority']}"
                print(f"{f['ticker']:<11} [label -> {f['classified_by']}] {result}  {f['summary'][:70]}")
    elif for_model:
        print(f"{len(for_model)} filings now need the model; run with --model to classify them")

    for f, cat, how, pri in changes:
        print(
            f"{f['ticker']:<11} {f['category']}/{f['priority']} [{f['classified_by']}]"
            f" -> {cat}/{pri} [{how}]  {f['text'][:70]}"
        )
    print(f"{len(changes)} filings {'would change' if a.dry_run else 'changed'}")


if __name__ == "__main__":
    main()
