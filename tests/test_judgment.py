"""Code that turns model output and numbers into verdicts. These rules are where a wrong word misleads an investor."""

import pytest

from backend import pull


def item(metric_key="revenue_growth", status="pending", check=None, revised_by=None):
    return {
        "metric_key": metric_key,
        "assessment": {"status": status},
        "check": check,
        "revised_by": revised_by,
    }


def test_growth_is_decided_by_numbers_over_the_model():
    v = pull._verdict(item(status="delivered", check={"status": "missed", "actual": 6.8, "basis": ""}))
    assert v == {"status": "missed", "judged_by": "numbers"}


def test_margin_rests_on_quotes_even_with_a_number():
    # Our margin excludes other income; companies guide on their own definition (RESEARCH R10).
    v = pull._verdict(item("operating_margin", "delivered", {"status": "off_track", "actual": 16.0, "basis": ""}))
    assert v == {"status": "delivered", "judged_by": "model"}


def test_margin_in_the_promised_definition_is_decided_by_numbers():
    check = {"status": "on_track", "actual": 21.0, "basis": "", "definition": "ebit"}
    assert pull._verdict(item("operating_margin", "pending", check)) == {"status": "on_track", "judged_by": "numbers"}


def test_a_later_call_that_settled_an_open_target_stands():
    # TCS "26% to 28%" in the coming quarters: a later call said it would not come; the latest quarter only says
    # off track
    check = {"status": "off_track", "actual": 24.0, "basis": "", "definition": "ebit"}
    assert pull._verdict(item("operating_margin", "missed", check)) == {"status": "missed", "judged_by": "model"}


def test_margins_rebuilt_from_filed_lines():
    # TCS Q2 FY27 filing; on the Oct 2026 call: "operating margin of 24%"
    tcs = {"revenue": 73188, "pbt": 18638, "finance_costs": 252, "depreciation": 1262, "other_income": 1337}
    assert pull._margin_of([tcs], "ebit") == 24.0
    assert pull._margin_of([tcs], "ebitda") == 25.7
    assert pull._margin_of([tcs], "pbdit") == 27.5
    assert pull._margin_kind("Operating margin", "TCS") == "ebit"  # IT services say operating margin for EBIT
    assert pull._margin_kind("Operating margin", "PIDILITIND") is None  # unsaid: left to the calls
    assert pull._margin_kind("Operating EBITDA margin", "HAL") == "ebitda"
    assert pull._margin_kind("PBDIT margin", "ASIANPAINT") == "pbdit"


def test_segment_names_match_across_filings():
    assert pull._seg_key("a) Wires & Cables") == pull._seg_key("Wires and cables") == "wires and cables"
    assert pull._seg_key("Jewellery (refer note 4)") == "jewellery"


def test_revision_only_replaces_an_open_verdict():
    assert pull._verdict(item(status="pending", revised_by="P7"))["status"] == "revised"
    assert pull._verdict(item(status="missed", revised_by="P7"))["status"] == "missed"


def test_a_promise_past_its_date_is_not_shown_as_not_due():
    # DIXON: "20% to 25% QoQ" phone volumes for Q2 FY27, still "Not due yet" after Q2 was reported
    assert pull._verdict({**item("other"), "due": "2026-09-30"})["status"] == "awaiting"
    assert pull._verdict({**item("other"), "due": "2099-03-31"})["status"] == "pending"
    assert pull._verdict(item("other"))["status"] == "pending"  # no date given


def test_shortfall_states_the_gap():
    assert pull._shortfall(6.8, 7.0) == ", 0.2 points below the 7% low end"
    assert pull._shortfall(7.0, 7.0) == ""
    assert pull._shortfall(12.5, 10.0) == ""


def test_cagr_written_as_a_total_is_rewritten():
    assert pull._yearly("Net profit grew 23% over 5 years.") == "Net profit grew 23% a year over 5 years."
    assert (
        pull._yearly("Revenue rose by 7.8% over the last five years")
        == "Revenue rose 7.8% a year over the last five years"
    )
    assert pull._yearly("PAT grew 33.8% YoY") == "PAT grew 33.8% YoY"
    assert pull._yearly("ROCE went from 10 percent to 15 percent") == "ROCE went from 10% to 15%"


def test_numbers_are_written_the_way_people_read_them():
    assert pull._n(607.0) == "607"
    assert pull._n(14.4) == "14.4"
    assert pull._n(5515.17) == "5,515"
    assert pull._n(None) == "n/a"


def test_people_headline_leads_with_the_senior_change():
    from backend.main import _people_headline

    def p(name, role, change, entity=None):
        return {"name": name, "role": role, "change": change, "entity": entity}

    icici = [
        p("Anup Bagchi", "Managing Director & CEO", "leaving", "ICICI Life Insurance Limited"),
        p("Sidharatha Mishra", "Managing Director & CEO", "joining", "ICICI Life Insurance Limited"),
        p("Sidharatha Mishra", "Senior Management Personnel", "leaving"),
    ]
    assert _people_headline(icici).startswith("ICICI Life Insurance Limited: Anup Bagchi leaves as Managing Director")
    assert _people_headline([p("Prithvi Vachani", "Executive Director", "joining")]) == (
        "Prithvi Vachani joins as Executive Director"
    )


def test_promise_timeframe_is_not_said_twice():
    from backend.pull import _when

    assert _when({"target": "ready by March", "timeframe": "by March"}) == ""
    assert _when({"target": "start up in next month", "timeframe": "next month"}) == ""
    assert _when({"target": "2x EBITDA", "timeframe": "FY29"}) == ", by FY29"
    assert _when({"target": "40 GWh", "timeframe": "within three years"}) == ", within three years"
    assert _when({"target": "40 GWh", "timeframe": None}) == ""


@pytest.mark.parametrize(
    "metric, company",
    [
        ("Revenue growth", True),
        ("Operating EBITDA margin", True),
        ("Exit operating margin", True),
        ("Full year value growth", True),
        ("Business Banking MSME loan growth", False),  # HDFCBANK: was judged against total revenue
        ("Jewellery revenue growth CAGR", False),  # TITAN: one division, not the company
        ("CaratLane EBIT margin", False),
        ("AUM growth", False),
    ],
)
def test_only_company_wide_targets_are_checked_against_company_numbers(metric, company):
    from backend.pull import _company_level

    assert _company_level(metric) is company


def _p(source, metric, quote, status, key="other"):
    return {"source": source, "metric": metric, "metric_key": key, "quote": quote, "status": status}


def test_a_new_call_reports_what_moved_and_what_is_new():
    old = {
        "transcripts": [{"period": "Jul 2026"}],
        "items": [
            _p("Jul 2026", "Retail EBITDA", "we expect to double retail EBITDA over three years", "pending"),
            _p("Jul 2026", "Jio IPO", "the listing should happen in the next few months", "pending"),
        ],
    }
    new = {
        "transcripts": [{"period": "Jul 2026"}, {"period": "Nov 2026"}],
        "items": [
            _p("Jul 2026", "Retail EBITDA", "we expect to double retail EBITDA over three years", "pending"),
            _p("Jul 2026", "Jio IPO", "the listing should happen in the next few months", "delivered"),
            _p("Nov 2026", "Battery plant", "the first battery line will start next quarter", "pending"),
        ],
    }
    u = {"call": "Nov 2026", **pull.ledger_changes(old, new)}
    assert u["moved"] == [{"metric": "Jio IPO", "from": "pending", "to": "delivered"}]
    assert u["added"] == 1
    assert pull.update_headline(u) == "Promise ledger after the Nov 2026 call: 1 now delivered, 1 new promise."
    assert pull.update_headline({"call": "Nov 2026", "moved": [], "added": 0}).endswith("no status changed.")
