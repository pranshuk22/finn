"""Business mix and balance sheet arithmetic, against a throwaway database."""

import json

import pytest


@pytest.fixture
def c(tmp_path, monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db", raising=False)
    db.init()
    with db.session() as conn:
        yield conn


def quarter(c, ticker, period_end, items, single=None):
    c.execute(
        "INSERT INTO results(ticker, period_end, consolidated, segments) VALUES(?,?,1,?)",
        (ticker, period_end, json.dumps({"single": single, "items": items})),
    )


def seg(name, revenue, result):
    return {"name": name, "revenue": revenue, "result": result}


def test_mix_margin_and_growth_against_the_same_quarter_last_year(c):
    from backend.analytics import segments

    quarter(c, "X", "2025-09-30", [seg("Retail", 300, 30), seg("Energy", 100, 10)])
    quarter(c, "X", "2026-09-30", [seg("Energy", 300, 60), seg("Retail", 300, 15), seg("New", 0, 0)])
    s = segments(c, "X")
    assert s["quarter"] == "Q2 FY27"
    assert [i["name"] for i in s["items"]] == ["Energy", "Retail"]  # largest first; an empty row is dropped
    energy, retail = s["items"]
    assert (energy["share_pct"], energy["margin_pct"], energy["yoy"]) == (50.0, 20.0, 200.0)
    assert energy["share_change_pts"] == 25.0  # 25% of segment revenue a year ago, 50% now
    assert (retail["margin_pct"], retail["yoy"], retail["share_change_pts"]) == (5.0, 0.0, -25.0)


def test_single_segment_company(c):
    from backend.analytics import segments

    quarter(c, "D", "2026-09-30", [], single="Electronic Goods")
    assert segments(c, "D")["single"] == "Electronic Goods" and segments(c, "D")["items"] == []


def test_balance_sheet_coverage_skips_a_half_year_column(c):
    from backend.analytics import balance_sheet

    rows = [
        ("balance-sheet", "Mar 2026", "Borrowings", 100),
        ("balance-sheet", "Mar 2026", "Equity Capital", 50),
        ("balance-sheet", "Mar 2026", "Reserves", 350),
        ("balance-sheet", "Mar 2026", "Other Liabilities", 500),
        ("balance-sheet", "Mar 2026", "Total Liabilities", 1000),
        ("balance-sheet", "Sep 2026", "Borrowings", 120),
        ("balance-sheet", "Sep 2026", "Equity Capital", 50),
        ("balance-sheet", "Sep 2026", "Reserves", 430),
        ("balance-sheet", "Sep 2026", "Total Liabilities", 1200),
        ("profit-loss", "Mar 2026", "Profit before tax", 180),
        ("profit-loss", "Mar 2026", "Interest", 20),
    ]
    c.executemany("INSERT INTO financials(ticker, statement, period, line_item, value) VALUES('X',?,?,?,?)", rows)
    b = balance_sheet(c, "X")
    mar, sep = b["years"]
    assert (mar["debt_to_equity"], mar["interest_coverage"]) == (0.25, 10.0)  # (180 + 20) / 20
    assert mar["mix"] == {"debt": 10.0, "equity": 40.0, "other": 50.0}
    assert sep["interest_coverage"] is None  # no full-year P&L for a half year
    assert b["interest_coverage"] == {"period": "Mar 2026", "value": 10.0}


def test_six_month_filing_becomes_a_quarter(c):
    # COFORGE Q2 FY27 filed six-month figures in both columns; Screener's Sep 2026 quarter: revenue 6,171, PAT 605
    from backend.jobs.refresh import to_quarter

    c.execute(
        "INSERT INTO results(ticker, period_end, consolidated, revenue, pbt, pat) VALUES(?,?,1,?,?,?)",
        ("COFORGE", "2026-06-30", 5527.7, 702.1, 531.7),
    )
    q = to_quarter(
        c, "COFORGE", 1, {"period_end": "2026-09-30", "months": 6, "revenue": 11698.5, "pbt": 1501.0, "pat": 1136.6}
    )
    assert (q["revenue"], q["pbt"], q["pat"]) == (6170.8, 798.9, 604.9)
    assert q["derived"].startswith("6 months")
    # without the earlier quarter the six-month figure is not passed off as a quarter
    assert to_quarter(c, "OTHER", 1, {"period_end": "2026-09-30", "months": 6, "revenue": 1.0}) is None
    assert to_quarter(c, "X", 1, {"period_end": "2026-09-30", "months": 3, "revenue": 1.0})["derived"] is None


def test_tax_note_when_tax_explains_the_profit_change():
    from backend.analytics import _tax_note

    # SUZLON Q2 FY27 against Q2 FY26: PAT was 227% of PBT a year ago (a tax credit)
    note = _tax_note({"pbt": 518.21, "pat": 394.15}, {"pbt": 562.5, "pat": 1279.44})
    assert note.startswith("PAT -69.2% YoY, but PBT -7.9%: a year ago tax was a credit (PAT was 227% of PBT), 24% now")
    # TCS: tax steady, PAT and PBT move together
    assert _tax_note({"pbt": 18638, "pat": 13934}, {"pbt": 16200, "pat": 12130}) is None


def test_a_gap_between_ebitda_and_pbt_is_explained():
    from backend.analytics import _below_ebitda

    # DIXON Q2 FY27 against Q2 FY26, from the NSE filings
    cur = {"other_income": 68.73, "finance_costs": 25.95, "depreciation": 110.06}
    yago = {"other_income": 495.74, "finance_costs": 38.35, "depreciation": 96.28}
    rows = [{"label": "EBITDA", "yoy": 6.3}, {"label": "PBT", "yoy": -42.6}]
    assert _below_ebitda(cur, yago, rows).startswith(
        "EBITDA +6.3% YoY while PBT -42.6%: other income fell from Rs 496 crore to Rs 69 crore."
    )
    assert _below_ebitda(cur, yago, [{"label": "EBITDA", "yoy": 6.3}, {"label": "PBT", "yoy": 10}]) is None


def test_bank_kpis_from_standalone_filing(c):
    """HDFCBANK Sep 2026 standalone filing: NII = 83,426.60 - 48,807.42 crore; NPA ratios as filed."""
    from backend import analytics as A

    _bank_rows(c)
    k = A.bank_kpis(c, "HDFCBANK")
    last = k["quarters"][-1]
    assert last["quarter"] == "Q2 FY27"
    assert last["nii"] == 34619.18
    assert last["nii_yoy"] == 9.7  # against 76,690.70 - 45,139.20 a year earlier
    assert last["gnpa_pct"] == 1.11 and last["nnpa_pct"] == 0.37 and last["cet1_pct"] == 18.87
    assert last["nii_to_assets"] == 3.02  # 34,619.18 x 4 / 45,77,759.77
    assert last["credit_cost"] == 0.45  # 3,573.62 x 4 / 31,95,566.06
    # a quarter without a balance sheet uses the last half-year's assets
    assert k["quarters"][0]["nii_to_assets"] is not None


def _bank_rows(c):
    rows = [
        ("2025-09-30", 76690.7, 45139.2, 3500.53, 2746359.78, 4003008.37, 1.24, 0.42, 19.96),
        ("2025-12-31", 76751.16, 44136.16, 2837.86, None, None, 1.24, 0.42, 19.87),
        ("2026-09-30", 83426.6, 48807.42, 3573.62, 3195566.06, 4577759.77, 1.11, 0.37, 18.87),
    ]
    for r in rows:
        c.execute(
            "INSERT INTO bank_kpis(ticker, period_end, interest_earned, interest_expended, provisions, advances,"
            " total_assets, gnpa_pct, nnpa_pct, cet1_pct) VALUES('HDFCBANK',?,?,?,?,?,?,?,?,?)",
            r,
        )


def test_parse_bank_kpis_drops_consolidated_zero_ratios():
    from backend.sources.nse import parse_bank_kpis

    def row(label, *v):
        return "<tr><td></td><td>" + label + "</td>" + "".join(f"<td>{x}</td>" for x in v) + "</tr>"

    html = (
        "<table>"
        + "<tr><td>Level of rounding used in financial results</td><td>Lakhs</td></tr>"
        + row("Date of end of reporting period", "30-09-2026")
        + row("Total interest earned", "95,13,163.00", "1,85,70,696.00")
        + row("% of gross NPAs", "0", "0")
        + row("CET 1 ratio", "18.8700", "18.8700")
        + "</table>"
    )
    k = parse_bank_kpis(html)
    assert k["interest_earned"] == 95131.63
    assert "gnpa_pct" not in k  # the consolidated filing's placeholder
    assert k["cet1_pct"] == 18.87


def _filed(c, ticker, period_end, revenue):
    c.execute(
        "INSERT INTO results(ticker, period_end, consolidated, revenue) VALUES(?,?,1,?)", (ticker, period_end, revenue)
    )


def test_full_year_revenue_target_against_the_quarters_filed(c):
    from backend import pull

    _filed(c, "X", "2026-06-30", 12000)
    _filed(c, "X", "2026-09-30", 13000)
    p = {"metric": "Total revenue", "target": "Rs 56,000 crore", "due": "2027-03-31", "unit": "rs_crore"}
    ch = pull._revenue_pace(c, "X", p, 56000, None)
    assert ch["status"] == "off_track"  # 25,000 in 2 quarters; an even pace needs 28,000
    assert "needs Rs 28,000 crore" in ch["basis"]
    # "ex-Vivo": FINN cannot take a part out of the filed total
    assert pull._revenue_pace(c, "X", {**p, "target": "INR 56,000 crores (ex-Vivo)"}, 56000, None) is None
    # a product line is not the company
    assert pull._revenue_pace(c, "X", {**p, "metric": "IT hardware revenue"}, 4000, None) is None


def test_segment_margin_target(c):
    from backend import pull

    quarter(c, "T", "2026-06-30", [seg("Jewellery (refer note 4)", 19002, 2360)])
    p = {"metric": "Jewellery EBIT margin", "metric_key": "operating_margin"}
    ch = pull._segment_check(c, "T", p, 11)
    assert ch["status"] == "on_track" and ch["actual"] == 12.4
    assert ch["basis"].startswith("Jewellery segment, Q1 FY27")
    # an EBITDA target above the segment's EBIT margin cannot be judged: EBITDA is higher by depreciation
    assert pull._segment_check(c, "T", {**p, "metric": "Jewellery EBITDA margin"}, 13) is None
