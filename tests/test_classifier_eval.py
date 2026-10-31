"""Regression test on the human-labelled filings in eval/ (EVIDENCE E27).

Runs only the deterministic stages (exchange label, text rules, priority rules) on the exchange text the labeller
saw. Filings those stages cannot place go to the model in production and are skipped here. Management changes are
skipped too: their priority comes from the people read out of the PDF, which needs the filing reader.
"""

import json
from pathlib import Path

import pytest

from backend.classify import by_label, by_rules, priority
from backend.enrich import is_senior, management_priority

EVAL = Path(__file__).parent.parent / "eval"


def cases():
    out = []
    for blind_file, label_file in (
        ("sample_blind.json", "filings_labelled.json"),
        ("holdout_blind.json", "holdout_labelled.json"),
    ):
        blind = {r["id"]: r for r in json.loads((EVAL / blind_file).read_text())}
        for x in json.loads((EVAL / label_file).read_text())["items"]:
            out.append((blind[x["id"]], x))
    return out


def deterministic(f):
    cat = by_label(f["nse_label"]) or by_rules(f["text"])
    return cat, (priority(cat, f["text"], f["nse_label"]) if cat else None)


def test_deterministic_stages_agree_with_human_labels():
    decided = agree_cat = agree_pri = 0
    misses = []
    for f, x in cases():
        cat, pri = deterministic(f)
        if cat is None or cat == "management_change":
            continue
        decided += 1
        ok_cat = cat in [x["category"], *x["category_alt"]]
        ok_pri = pri in [x["priority"], *x["priority_alt"]]
        agree_cat += ok_cat
        agree_pri += ok_pri
        if not (ok_cat and ok_pri):
            misses.append(f"{x['ticker']} {f['text'][:60]!r}: {cat}/{pri} vs {x['category']}/{x['priority']}")
    assert decided >= 50, "the deterministic stages should still place most filings"
    assert agree_cat / decided >= 0.95, misses
    assert agree_pri / decided >= 0.93, misses


@pytest.mark.parametrize(
    "role, senior",
    [
        ("Managing Director & CEO", True),
        ("Deputy Managing Director", True),
        ("Chief Financial Officer", True),
        ("Whole Time Director", True),
        ("Executive Director", True),
        ("Non-executive Independent Director", False),
        ("Senior Management Personnel", False),
        ("President & Head - India Sales", False),
        ("Chief Product Officer", False),
    ],
)
def test_seniority_is_decided_from_the_role(role, senior):
    assert is_senior(role) is senior


def test_management_priority_follows_the_readme_policy():
    p = lambda name, role, change, entity=None: {"name": name, "role": role, "change": change, "entity": entity}  # noqa: E731
    assert management_priority([p("A", "Chief Executive Officer", "leaving")]) == "needs_you"
    assert (
        management_priority([p("B", "Managing Director & CEO", "joining", "ICICI Life Insurance Limited")])
        == "worth_knowing"
    )
    assert management_priority([p("C", "Non-executive Independent Director", "joining")]) == "worth_knowing"
    assert management_priority([p("D", "Whole Time Director", "reappointed")]) == "routine"
    assert management_priority([]) == "worth_knowing"
