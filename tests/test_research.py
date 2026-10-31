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
