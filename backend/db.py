"""SQLite storage. Ingest jobs write; the API only reads."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from backend.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS filings (
    id TEXT PRIMARY KEY,              -- NSE seq_id
    ticker TEXT NOT NULL,
    an_dt TEXT NOT NULL,              -- ISO timestamp, IST
    nse_label TEXT,
    text TEXT,                        -- company's own one-line summary
    pdf_url TEXT,
    category TEXT,
    priority TEXT,                    -- needs_you | worth_knowing | routine
    summary TEXT,                     -- one line shown on the card
    classified_by TEXT,               -- label | rule | model
    enrichment TEXT                   -- JSON, e.g. results table or bio
);
CREATE INDEX IF NOT EXISTS filings_dt ON filings(an_dt);

CREATE TABLE IF NOT EXISTS eod (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS results (
    ticker TEXT NOT NULL,
    period_end TEXT NOT NULL,         -- ISO date
    consolidated INTEGER NOT NULL,
    revenue REAL, total_income REAL, other_income REAL, finance_costs REAL, depreciation REAL,
    ppop REAL, provisions REAL,       -- banks only: pre-provision operating profit, provisions
    pbt REAL, pat REAL,               -- all in Rs crore
    is_bank INTEGER NOT NULL DEFAULT 0,
    broadcast_at TEXT,
    source_url TEXT,
    segments TEXT,                    -- JSON from the same filing: {single, items: [{name, revenue, result}]}
    PRIMARY KEY (ticker, period_end, consolidated)
);

CREATE TABLE IF NOT EXISTS financials (
    ticker TEXT NOT NULL,
    statement TEXT NOT NULL,          -- quarters | profit-loss | balance-sheet | cash-flow | ratios
    period TEXT NOT NULL,             -- e.g. "Sep 2026" or "Mar 2026"
    line_item TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (ticker, statement, period, line_item)
);

CREATE TABLE IF NOT EXISTS companies (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    about TEXT,
    ratios TEXT,                      -- JSON, Screener top ratios (market cap, P/E, ROCE...)
    statement_mode TEXT,              -- consolidated | standalone
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    ticker TEXT NOT NULL,
    kind TEXT NOT NULL,               -- transcript | annual_report
    period TEXT NOT NULL,             -- e.g. "Oct 2026" or "2026"
    url TEXT NOT NULL,
    pages TEXT,                       -- JSON list of page texts, null until downloaded
    PRIMARY KEY (ticker, kind, period)
);

CREATE TABLE IF NOT EXISTS research (
    ticker TEXT NOT NULL,
    section TEXT NOT NULL,
    payload TEXT NOT NULL,            -- JSON
    built_at TEXT NOT NULL,
    PRIMARY KEY (ticker, section)
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT, model TEXT,
    tokens_in INTEGER, tokens_out INTEGER, tokens_cached INTEGER, tokens_thinking INTEGER,
    latency_ms INTEGER, ok INTEGER, ts TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added after a table was first created: CREATE TABLE IF NOT EXISTS leaves old tables as they were.
_ADDED = [("results", "segments", "TEXT")]


def init() -> None:
    with session() as c:
        c.executescript(SCHEMA)
        for table, col, kind in _ADDED:
            if col not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def set_meta(c: sqlite3.Connection, key: str, value) -> None:
    c.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def get_meta(c: sqlite3.Connection, key: str, default=None):
    row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default
