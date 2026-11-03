"""The recorded evals still score as reported in the README. Scoring is offline: it reads saved answers and labels."""

import json
from pathlib import Path

from eval import ask_eval, ledger_eval

HERE = Path(__file__).parent.parent / "eval"


def _ask(path: str) -> dict:
    questions = json.loads((HERE / "ask_set.json").read_text())["questions"]
    return ask_eval.report(questions, json.loads((HERE / path).read_text()))


def test_ask_eval_as_reported():
    assert _ask("ask_answers.json")["passed"] == 31  # context mode, the default
    assert _ask("ask_answers_agent.json")["passed"] == 30  # agent mode, behind FINN_ASK=agent


def test_scorer_reads_numbers_as_whole_tokens():
    assert ask_eval._has("other income was 30.2% of PBT", "30.2")
    assert not ask_eval._has("other income was 130.2% of PBT", "30.2")
    assert ask_eval._has("PAT was Rs 29,550 crore", "29,550")
    q = {"kind": "refuse", "expect": []}
    assert ask_eval.score_one(q, {"covered": False, "answer": "", "citations": [], "figures": []})[0]


def test_ledger_eval_as_reported():
    r = ledger_eval.report()
    assert (r["n"], r["target_ok"], r["correct"], r["conservative"], r["overclaim"]) == (20, 18, 16, 1, 3)
