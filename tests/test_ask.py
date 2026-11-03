"""Ask answers number questions from the reported results first, and every number it writes is traced to a source.

On 1 Nov "What are the profits?" for RELIANCE came back from the calls alone: the Q1 group profit, then the
retail and Jio subsidiaries' profits, with the Q2 results (filed two days earlier) missing.
"""

import pytest

from backend import pull


@pytest.fixture
def c(tmp_path, monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db", raising=False)
    db.init()
    with db.session() as conn:
        yield conn


def result(c, period_end, revenue, pbt, pat):
    c.execute(
        "INSERT INTO results(ticker, period_end, consolidated, revenue, pbt, pat, is_bank, source_url)"
        " VALUES('X',?,1,?,?,?,0,?)",
        (period_end, revenue, pbt, pat, f"https://nse/{period_end}"),
    )


def test_latest_quarter_is_stated_as_consolidated_pat_with_its_filing(c):
    result(c, "2025-09-30", 1000, 200, 150)
    result(c, "2026-06-30", 1100, 220, 160)
    result(c, "2026-09-30", 1200, 260, 195)
    figs = pull._reported(c, "X")
    pat = next(f for f in figs.values() if "PAT (net profit)" in f["text"] and "by quarter" not in f["text"])
    assert pat["text"].startswith("Q2 FY27 (quarter ended 30 Sep 2026), consolidated PAT (net profit): Rs 195 crore")
    assert "YoY 30%" in pat["text"]
    assert (pat["source"], pat["url"]) == ("Q2 FY27 results filing", "https://nse/2026-09-30")


def test_numbers_must_come_from_a_cited_source():
    sources = ["Q2 FY27 consolidated PAT (net profit): Rs 29,550 crore, YoY 33.8%", "Revenue Rs 332,861 crore"]
    answer = "Q2 FY27 PAT was Rs 29,550 crore, up 34% from 2025, on revenue of Rs 3.33 lakh crore. Retail made 4,300."
    # 34 is 33.8 rounded, 3.33 lakh crore is 332,861 crore, Q2 FY27 and 2025 are labels; 4,300 is in no source
    assert pull.unmatched_numbers(answer, sources) == ["4,300"]
    # the DIXON case: an older call's growth rate is close to the filed one, but it is not the filed one
    assert pull.unmatched_numbers("Revenue grew 39.7% YoY", ["Revenue YoY 40.2%"]) == ["39.7"]


def test_small_decimals_are_checked_and_lakh_crore_only_when_said():
    # ICICIBANK, 3 Nov: "NIM was 4.18%" stayed on screen after its quote failed. Numbers under 10 were skipped as
    # counts, and 4.18 also matched a Rs 4,18,000 crore figure read as lakh crore.
    sources = ["Total assets Rs 4,18,000 crore"]
    assert pull.unmatched_numbers("NIM was 4.18% against 4.36%.", sources) == ["4.18", "4.36"]
    assert pull.unmatched_numbers("Assets are Rs 4.18 lakh crore.", sources) == []
    assert pull.unmatched_numbers("It reported 3 segments on two calls.", []) == []  # a small whole number is a count


def test_a_sentence_with_an_unbacked_number_is_removed():
    answer = 'Q2 FY27 PAT was Rs 195 crore. Management said "margins hit 18.5%" on the call. Demand was strong.'
    assert pull._drop_unbacked(answer, ["18.5"]) == ("Q2 FY27 PAT was Rs 195 crore. Demand was strong.", 1)
    assert pull._drop_unbacked(answer, []) == (answer, 0)


def ask_with(monkeypatch, figures, citations, covered=True):
    figs = {"R1": {"text": "Q2 FY27 PAT Rs 195 crore", "source": "Q2 FY27 results filing", "url": "u"}}
    monkeypatch.setattr(pull, "load_transcripts", lambda t: [])
    monkeypatch.setattr(pull, "_reported", lambda c, t: figs)
    answer = pull.Answer(covered=covered, answer="PAT was Rs 195 crore [R1].", figures=figures, citations=citations)
    seen = {}

    def generate(**kw):
        seen.update(kw)
        return answer

    monkeypatch.setattr(pull.llm, "generate", generate)
    return pull.ask("X", "What are the profits?"), seen


def test_an_answer_backed_by_a_reported_figure_stands_without_a_quote(c, monkeypatch):
    out, seen = ask_with(monkeypatch, ["R1", "R1", "R9"], [])
    assert "REPORTED FIGURES\n[R1] Q2 FY27 PAT Rs 195 crore" in seen["contents"]
    assert out["covered"] and not out["unverified"]
    assert [f["id"] for f in out["figures"]] == ["R1"]  # duplicate and unknown ids dropped
    assert out["unmatched_numbers"] == []
    assert out["answer"] == "PAT was Rs 195 crore."  # the model's "[R1]" pointer is not shown to the reader


def test_an_answer_with_no_traceable_source_is_withheld(c, monkeypatch):
    out, _ = ask_with(monkeypatch, ["R9"], [])
    assert out["unverified"] and not out["covered"]
    assert "not giving one" in out["answer"]


def test_a_beginner_question_shows_the_definition_it_rests_on(c, monkeypatch):
    # "What does EBITDA mean?" on DIXON, 3 Nov: answered from FINN's glossary, so the glossary entry is shown with it
    out, seen = ask_with(monkeypatch, ["R1"], [])
    assert "GLOSSARY" in seen["contents"] and "EBITDA: operating EBITDA" in seen["contents"]
    out = pull.ask("X", "What does EBITDA mean?")
    assert any(f["source"] == "FINN's glossary" and f["text"].startswith("EBITDA:") for f in out["figures"])


def test_note_keeps_only_sentences_backed_by_the_facts_they_cite(monkeypatch):
    facts = {
        "N1": "Q2 FY27 explanation: EBITDA +6.3% YoY while PBT -42.6%: other income fell from Rs 496 crore to "
        "Rs 69 crore.",
        "N2": "Q2 FY27 EBITDA margin: 2.7%, change on a year earlier -104 bps",
        "N3": "Q2 FY27 PAT: Rs 411 crore, QoQ -42.8%, YoY -44.9%",
    }
    rc = {"period_end": "2026-09-30", "quarter": "Q2 FY27"}
    monkeypatch.setattr(pull, "_note_facts", lambda c, t: (rc, facts))
    lines = [
        pull.NoteLine(text="PBT fell 42.6% because other income fell from Rs 496 crore to Rs 69 crore.", refs=["N1"]),
        pull.NoteLine(text="Watch the margin, which fell by -104 bps to 2.7%.", refs=["N2"]),
        pull.NoteLine(text="Phones grew 60% this quarter.", refs=["N3"]),  # 60 is in no cited fact
    ]
    monkeypatch.setattr(pull.llm, "generate", lambda **kw: pull.Note(sentences=lines))
    note = pull.build_note("DIXON")
    assert [s["text"] for s in note["sentences"]] == [
        "PBT fell 42.6% because other income fell from Rs 496 crore to Rs 69 crore.",
        "Watch the margin, which fell by 104 bps to 2.7%.",
    ]
    lines[:] = [pull.NoteLine(text="Margins look fine.", refs=["N9"])]  # cites nothing real
    assert pull.build_note("DIXON") is None
