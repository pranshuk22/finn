"""Ask eval: run the questions in ask_set.json against FINN and score the answers.

uv run python -m eval.ask_eval --run      # ask the live app, save answers to ask_answers.json, then score
uv run python -m eval.ask_eval            # score the saved answers (what CI does)
uv run python -m eval.ask_eval --local agent    # run one Ask mode in-process on local data, to compare modes

The answers come from the deployed app end to end (https://finn-mu-three.vercel.app), so the eval measures what a
user gets: retrieval, the model, and the guards that check quotes and numbers.
"""

import argparse
import json
import re
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
BASE = "https://finn-mu-three.vercel.app"
SET = HERE / "ask_set.json"
ANSWERS = HERE / "ask_answers.json"


def _norm(s: str) -> str:
    return s.replace(",", "").lower()


def _has(answer: str, want: str) -> bool:
    """A number must appear as a whole number token ("30" is not found in "130"); words match anywhere."""
    if re.fullmatch(r"[\d,.]+", want):
        return re.search(rf"(?<![\d.]){re.escape(_norm(want))}(?![\d]|\.\d)", _norm(answer)) is not None
    return want.lower() in answer.lower()


def score_one(q: dict, a: dict) -> tuple[bool, str]:
    """(passed, why) for one question under the rule its kind names in ask_set.json."""
    if "error" in a:
        return False, f"request failed: {a['error']}"
    text, covered = a.get("answer", ""), a.get("covered", False)
    cites, figs = a.get("citations", []), a.get("figures", [])
    missing = [w for w in q.get("expect", []) if not _has(text, w)]
    kind = q["kind"]
    if kind == "refuse":
        return (not covered), "said not covered" if not covered else "answered a question the sources cannot answer"
    if not covered:
        return False, "said not covered"
    if missing:
        return False, f"missing {', '.join(missing)}"
    if kind == "glossary" and not any(f.get("source") == "FINN's glossary" for f in figs):
        return False, "no glossary entry shown"
    if kind == "quote" and not any(not c["source"].startswith("Annual report") for c in cites):
        return False, "no verified quote from a call"
    if kind == "annual_report" and not any(c["source"].startswith("Annual report") for c in cites):
        return False, "no verified quote from the annual report"
    return True, "ok"


def run(questions: list[dict]) -> list[dict]:
    out = []
    with httpx.Client(timeout=120) as client:
        for q in questions:
            t0 = time.time()
            try:
                r = client.post(f"{BASE}/api/research/{q['ticker']}/ask", json={"question": q["q"]})
                r.raise_for_status()
                a = r.json()
            except Exception as e:  # noqa: BLE001  record it and move on; a failure scores as a miss
                a = {"error": str(e)}
            a["seconds"] = round(time.time() - t0, 1)
            out.append({"id": q["id"], **a})
            print(f"{q['id']:>4} {a['seconds']:>5}s  {q['q']}", flush=True)
            time.sleep(4)  # the free tier allows 15 requests a minute per model
    return out


def run_local(questions: list[dict], mode: str) -> list[dict]:
    from backend import db, pull

    fn = pull.ask_agent if mode == "agent" else pull.ask_context
    with db.session() as c:
        start = c.execute("SELECT COALESCE(MAX(id), 0) FROM llm_calls").fetchone()[0]
    out = []
    for q in questions:
        t0 = time.time()
        try:
            a = fn(q["ticker"], q["q"])
        except Exception as e:  # noqa: BLE001
            a = {"error": str(e)}
        a["seconds"] = round(time.time() - t0, 1)
        out.append({"id": q["id"], **a})
        print(f"{q['id']:>4} {a['seconds']:>5}s  {q['q']}", flush=True)
    with db.session() as c:
        calls, tokens = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(tokens_in), 0) FROM llm_calls WHERE id > ? AND ok = 1", (start,)
        ).fetchone()
    print(f"\n{mode}: {calls} model calls, {tokens:,} tokens in")
    return out


def report(questions: list[dict], answers: list[dict]) -> dict:
    by_id = {a["id"]: a for a in answers}
    rows, totals = [], {}
    for q in questions:
        ok, why = score_one(q, by_id.get(q["id"], {"error": "not run"}))
        rows.append((q, ok, why))
        t = totals.setdefault(q["kind"], [0, 0])
        t[0] += ok
        t[1] += 1
    passed = sum(ok for _, ok, _ in rows)
    removed = sum(1 for a in answers if a.get("removed_sentences"))
    dropped = sum(a.get("unverified_dropped") or 0 for a in answers)
    secs = sorted(a["seconds"] for a in answers if "seconds" in a)
    print(f"\nAsk eval: {passed} of {len(rows)} passed")
    for kind, (p, n) in totals.items():
        print(f"  {kind:<14} {p} of {n}")
    print(f"  guard: {removed} answers had a sentence removed for a number in no source; {dropped} quotes dropped")
    if secs:
        print(f"  median answer time {secs[len(secs) // 2]} s")
    for q, ok, why in rows:
        if not ok:
            print(f"  MISS {q['id']} {q['ticker']}: {q['q']} ({why})")
    return {"passed": passed, "total": len(rows), "by_kind": totals}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="ask the live app and save the answers first")
    ap.add_argument("--local", choices=["context", "agent"], help="run one Ask mode in-process instead")
    a = ap.parse_args()
    questions = json.loads(SET.read_text())["questions"]
    if a.local:
        path = ANSWERS if a.local == "context" else HERE / "ask_answers_agent.json"
        path.write_text(json.dumps(run_local(questions, a.local), indent=1, ensure_ascii=False) + "\n")
        report(questions, json.loads(path.read_text()))
        return
    if a.run:
        ANSWERS.write_text(json.dumps(run(questions), indent=1, ensure_ascii=False) + "\n")
    report(questions, json.loads(ANSWERS.read_text()))


if __name__ == "__main__":
    main()
