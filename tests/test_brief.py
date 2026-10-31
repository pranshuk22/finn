"""The brief's grouping and ordering, against a throwaway database."""

import json

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db", raising=False)
    db.init()
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app), db


def add(db, id, ticker, cat, prio, at, summary="s", enrichment=None):
    with db.session() as c:
        c.execute(
            "INSERT INTO filings(id, ticker, an_dt, nse_label, text, pdf_url, category, priority, summary,"
            " classified_by, enrichment) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (id, ticker, at, "", "", None, cat, prio, summary, "label", json.dumps(enrichment) if enrichment else None),
        )


def recent(minutes):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    t = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None) - timedelta(minutes=minutes)
    return t.isoformat(timespec="seconds")


def test_grouping_priority_and_routine(client):
    tc, db = client
    add(db, 1, "TCS", "dividend", "worth_knowing", recent(30))
    add(db, 2, "TCS", "litigation", "needs_you", recent(60))
    add(db, 3, "TCS", "litigation", "worth_knowing", recent(90))  # same company and category: one card
    add(db, 4, "INFY", "press_release", "routine", recent(10))
    b = tc.get("/api/brief?hours=24").json()
    assert [k["category"] for k in b["needs_you"]] == ["litigation"]
    assert len(b["needs_you"][0]["filings"]) == 2
    assert [k["category"] for k in b["worth_knowing"]] == ["dividend"]
    assert b["routine"]["count"] == 1


def test_amount_only_on_deal_type_cards(client):
    tc, db = client
    add(
        db,
        5,
        "MAXHEALTH",
        "management_change",
        "needs_you",
        recent(5),
        enrichment={"amount_rs_crore": 1143.0, "people": []},
    )
    b = tc.get("/api/brief?hours=24").json()
    assert b["needs_you"][0]["scale"] is None


def test_portfolio_day_breadth_and_extremes(client):
    from backend import analytics as A

    _, db = client
    rows = [
        ("AAA", "2026-10-28", 100.0),
        ("AAA", "2026-10-29", 105.0),  # +5%
        ("BBB", "2026-10-28", 200.0),
        ("BBB", "2026-10-29", 196.0),  # -2%
        ("CCC", "2026-10-28", 50.0),
        ("CCC", "2026-10-29", 50.5),  # +1%
        ("DDD", "2026-10-27", 10.0),
        ("DDD", "2026-10-28", 11.0),  # no row on the latest day: left out
    ]
    with db.session() as c:
        c.executemany("INSERT INTO eod(ticker, date, close, volume) VALUES(?,?,?,1000)", rows)
        day = A.portfolio_day(c, ["AAA", "BBB", "CCC", "DDD"])
    assert day == {
        "date": "2026-10-29",
        "count": 3,
        "of": 4,
        "up": 2,
        "down": 1,
        "median_pct": 1.0,
        "best": {"ticker": "AAA", "move_pct": 5.0},
        "worst": {"ticker": "BBB", "move_pct": -2.0},
    }


def test_reaction_uses_the_first_session_after_the_filing(client):
    from backend import analytics as A

    _, db = client
    days = [("2026-10-26", 100.0, 1000), ("2026-10-27", 102.0, 1000), ("2026-10-28", 96.9, 3000)]
    with db.session() as c:
        c.executemany("INSERT INTO eod(ticker, date, close, volume) VALUES('ZZZ',?,?,?)", days)
        before_close = A.reaction(c, "ZZZ", "2026-10-27T11:00:00")
        after_close = A.reaction(c, "ZZZ", "2026-10-27T17:30:00")
        not_yet = A.reaction(c, "ZZZ", "2026-10-28T18:00:00")
    assert before_close["session"] == "same day" and before_close["move_pct"] == 2.0
    assert after_close["session"] == "next session" and after_close["move_pct"] == -5.0
    assert after_close["vol_mult"] == 3.0
    assert not_yet == {"pending": True, "session": "next session"}


def test_people_levels():
    from backend.main import _level

    assert _level("Managing Director & CEO") == "top"
    assert _level("Non-executive Independent Director") == "board"
    assert _level("Chief Product Officer") == "staff"
