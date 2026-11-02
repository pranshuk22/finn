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
        "stocks": [  # best to worst, for the chart in the hero
            {"ticker": "AAA", "move_pct": 5.0},
            {"ticker": "CCC", "move_pct": 1.0},
            {"ticker": "BBB", "move_pct": -2.0},
        ],
    }


def test_price_chart_places_a_filing_on_the_session_it_could_move(client):
    from backend.main import _price_story

    _, db = client
    days = [f"2026-10-{d:02d}" for d in range(1, 31) if d not in (4, 5, 11, 12, 18, 19, 25, 26)]
    with db.session() as c:
        c.executemany("INSERT INTO eod(ticker, date, close, volume) VALUES('AAA',?,100,1000)", [(d,) for d in days])
    add(db, 1, "AAA", "results", "worth_knowing", "2026-10-22T14:10:00")  # in market hours: same session
    add(db, 2, "AAA", "litigation", "needs_you", "2026-10-22T16:20:00")  # after the close: next session
    add(db, 3, "AAA", "M&A", "worth_knowing", "2026-10-25T11:00:00")  # a Sunday: Monday's session
    add(db, 4, "AAA", "dividend", "routine", "2026-10-21T10:00:00")  # routine: not marked
    with db.session() as c:
        story = _price_story(c, "AAA")
    placed = {e["date"]: [f["category_label"] for f in e["filings"]] for e in story["events"]}
    assert placed == {"2026-10-22": ["Results"], "2026-10-23": ["Litigation"], "2026-10-27": ["M&A"]}


def test_reaction_uses_the_first_session_after_the_filing(client):
    from backend import analytics as A

    _, db = client
    days = [("2026-10-26", 100.0, 1000), ("2026-10-27", 102.0, 1000), ("2026-10-28", 96.9, 3000)]
    with db.session() as c:
        c.executemany("INSERT INTO eod(ticker, date, close, volume) VALUES('ZZZ',?,?,?)", days)
        before_close = A.reaction(c, "ZZZ", "2026-10-27T11:00:00")
        after_close = A.reaction(c, "ZZZ", "2026-10-27T17:30:00")
        missing = A.reaction(c, "ZZZ", "2026-10-28T18:00:00")  # Thursday 29 Oct has closed; no price stored
        weekend = A.reaction(c, "ZZZ", "2030-01-04T18:00:00")  # a Friday evening: the next session is Monday
    assert before_close["session"] == "same day" and before_close["move_pct"] == 2.0
    assert after_close["session"] == "next session" and after_close["move_pct"] == -5.0
    assert after_close["vol_mult"] == 3.0
    assert missing == {"pending": True, "state": "not_loaded", "date": "2026-10-29"}
    assert weekend == {"pending": True, "state": "upcoming", "date": "2030-01-07"}


def test_people_levels():
    from backend.main import _level

    assert _level("Managing Director & CEO") == "top"
    assert _level("Non-executive Independent Director") == "board"
    assert _level("Chief Product Officer") == "staff"


def test_a_monday_brief_starts_at_fridays_close(client, monkeypatch):
    # 2 Nov 2026: "24 hours" started Sunday night, so Friday evening's results behind Monday's moves were missing.
    from datetime import datetime

    from backend import main

    _, db = client
    with db.session() as c:
        c.executemany(
            "INSERT INTO eod(ticker, date, close, volume) VALUES('AAA',?,100,1000)",
            [("2026-10-29",), ("2026-10-30",), ("2026-11-02",)],
        )
        monkeypatch.setattr(main, "_now", lambda: datetime(2026, 11, 2, 22, 30))
        assert main._window(c, 24) == (datetime(2026, 10, 30, 15, 30), 1)  # Monday's session, news since Friday
        assert main._window(c, 72) == (datetime(2026, 10, 29, 15, 30), 2)
        # prices a week stale do not drag the window back with them
        monkeypatch.setattr(main, "_now", lambda: datetime(2026, 11, 12, 22, 30))
        assert main._window(c, 24) == (datetime(2026, 11, 11, 22, 30), 1)


def test_one_person_named_two_ways_is_listed_once(client):
    tc, db = client
    p = {"role": "Managing Director and Chief Executive Officer", "change": "joining"}
    add(
        db,
        1,
        "HDFCBANK",
        "management_change",
        "needs_you",
        recent(30),
        enrichment={"people": [{**p, "name": "Anup Bagchi"}]},
    )
    add(
        db,
        2,
        "HDFCBANK",
        "management_change",
        "needs_you",
        recent(20),
        enrichment={"people": [{**p, "name": "Mr. Anup Bagchi"}]},
    )
    card = tc.get("/api/brief?hours=24").json()["needs_you"][0]
    assert len(card["people"]) == 1


def test_amount_read_from_the_summary_when_the_pdf_was_not_read():
    from backend import main

    # ICICIBANK, 1 Nov: "Appellate authority reduced tax penalty to 6.95 lakh rupees." kept an Alert tag
    assert main._amount_in("Appellate authority reduced tax penalty to 6.95 lakh rupees.") == 0.0695
    assert main._amount_in("Order worth Rs 1,250 crore") == 1250
    assert main._amount_in("Board meeting on 30 Oct") is None
