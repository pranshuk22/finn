from pathlib import Path

from backend.sources.nse import parse_results_ixbrl

FIX = Path(__file__).parent / "fixtures"


def test_tcs_q2fy27_matches_screener():
    # Screener's quarterly table for Sep 2026: Sales 73,188, PBT 18,638, Net Profit 13,934
    r = parse_results_ixbrl((FIX / "tcs_q2fy27_ixbrl.html").read_text())
    assert r["period_end"] == "2026-09-30"
    assert r["unit_in_filing"] == "lakhs"
    assert (r["revenue"], r["pbt"], r["pat"]) == (73188.0, 18638.0, 13934.0)
    assert not r["is_bank"]
    # EBITDA derived as PBT + finance costs + depreciation - other income = Screener's 18,815
    assert r["pbt"] + r["finance_costs"] + r["depreciation"] - r["other_income"] == 18815.0


def test_bank_layout_has_ppop_not_ebitda_inputs():
    r = parse_results_ixbrl((FIX / "hdfcbank_q2fy27_ixbrl.html").read_text())
    assert r["is_bank"]
    assert r["ppop"] == 32871.54 and r["provisions"] == 4209.0
    assert "depreciation" not in r
