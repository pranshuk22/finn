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
