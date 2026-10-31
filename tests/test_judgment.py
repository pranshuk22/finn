"""Code that turns model output and numbers into verdicts. These rules are where a wrong word misleads an investor."""

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
    # Our margin excludes other income; companies guide on their own definition (EVIDENCE E20).
    v = pull._verdict(item("operating_margin", "delivered", {"status": "off_track", "actual": 16.0, "basis": ""}))
    assert v == {"status": "delivered", "judged_by": "model"}


def test_revision_only_replaces_an_open_verdict():
    assert pull._verdict(item(status="pending", revised_by="P7"))["status"] == "revised"
    assert pull._verdict(item(status="missed", revised_by="P7"))["status"] == "missed"


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
