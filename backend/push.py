"""Web Push: alerts reach the phone when FINN finds them, not when the app is next opened.

The server signs each message with its own VAPID key (RFC 8292), created once and kept in data/. Browsers hand
FINN a subscription (an endpoint at Google, Mozilla or Apple plus keys); FINN stores it and posts encrypted
messages to it after each refresh. On an iPhone this works once FINN is added to the Home Screen (iOS 16.4+).
"""

import base64
import json
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend import analytics as A
from backend import db
from backend.config import DATA_DIR, PORTFOLIO

KEY_PATH = DATA_DIR / "vapid_private.pem"
CLAIMS = {"sub": "https://finn-mu-three.vercel.app"}
FRESH = timedelta(hours=3)  # a filing older than this when first seen is not news any more
MAX_LINES = 3  # beyond this, one message names the rest by ticker

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, sub TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS push_sent (key TEXT PRIMARY KEY, at TEXT NOT NULL);
"""


def _private_key() -> ec.EllipticCurvePrivateKey:
    if not KEY_PATH.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        KEY_PATH.write_bytes(pem)
        KEY_PATH.chmod(0o600)
    return serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)


def public_key() -> str:
    """The key the browser needs to subscribe: the uncompressed P-256 point, base64url without padding."""
    point = serialization.PublicFormat.UncompressedPoint
    raw = _private_key().public_key().public_bytes(serialization.Encoding.X962, point)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subscribe(sub: dict) -> None:
    with db.session() as c:
        c.executescript(SCHEMA)
        c.execute(
            "INSERT OR REPLACE INTO push_subs(endpoint, sub, created_at) VALUES(?,?,?)",
            (sub["endpoint"], json.dumps(sub), db.now_iso()),
        )


def unsubscribe(endpoint: str) -> None:
    with db.session() as c:
        c.executescript(SCHEMA)
        c.execute("DELETE FROM push_subs WHERE endpoint=?", (endpoint,))


def send(sub: dict, title: str, body: str, url: str = "/", tag: str | None = None) -> bool:
    """True if the push service took it. A subscription the service says is gone (404, 410) is removed."""
    from pywebpush import WebPushException, webpush

    _private_key()  # created on first use
    try:
        webpush(
            subscription_info=sub,
            data=json.dumps({"title": title, "body": body, "url": url, "tag": tag}),
            vapid_private_key=str(KEY_PATH),
            vapid_claims=dict(CLAIMS),
            ttl=12 * 3600,
        )
        return True
    except WebPushException as e:
        if e.response is not None and e.response.status_code in (404, 410):
            unsubscribe(sub["endpoint"])
        return False


def _subs(c) -> list[dict]:
    c.executescript(SCHEMA)
    return [json.loads(r["sub"]) for r in c.execute("SELECT sub FROM push_subs")]


def pending(c, rules: dict, now: datetime | None = None) -> list[dict]:
    """Alerts not sent yet: new filings that need you or are in a flagged category, and the latest session's
    price or volume moves past the thresholds. Each has a key so it is sent once."""
    c.executescript(SCHEMA)
    now = now or datetime.now(UTC)
    sent = {r["key"] for r in c.execute("SELECT key FROM push_sent")}
    out = []
    since = (now - FRESH).astimezone(A.IST).replace(tzinfo=None).isoformat(timespec="seconds")
    flagged = set(rules.get("categories", []))
    for f in c.execute(
        "SELECT id, ticker, summary, category, priority, an_dt FROM filings WHERE an_dt >= ? ORDER BY an_dt", (since,)
    ):
        if f["priority"] != "needs_you" and f["category"] not in flagged:
            continue
        if f"filing:{f['id']}" in sent:
            continue
        out.append({"key": f"filing:{f['id']}", "ticker": f["ticker"], "line": f"{f['ticker']}: {f['summary']}"})
    last = c.execute("SELECT MAX(date) FROM eod").fetchone()[0]
    if last:
        for h in A.eod_scan(c, list(PORTFOLIO), rules.get("price_pct", 3.0), rules.get("vol_mult", 2.0), days=1):
            key = f"eod:{h['ticker']}:{h['date']}"
            if h["date"] != last or key in sent:
                continue
            vol = f" on {h['vol_mult']:.1f}x usual volume" if h["vol_mult"] else ""
            out.append({"key": key, "ticker": h["ticker"], "line": f"{h['ticker']} {h['move_pct']:+.1f}%{vol}"})
    return out


def message(alerts: list[dict]) -> tuple[str, str]:
    if len(alerts) == 1:
        return "FINN alert", alerts[0]["line"]
    lines = [a["line"] for a in alerts[:MAX_LINES]]
    rest = sorted({a["ticker"] for a in alerts[MAX_LINES:]})
    if rest:
        lines.append(f"Also: {', '.join(rest)}")
    return f"{len(alerts)} FINN alerts", "\n".join(lines)


def notify() -> int:
    """Called after each refresh. Sends one message per phone for everything new, then marks it sent."""
    with db.session() as c:
        rules = db.get_meta(c, "alert_rules", {}) or {}
        alerts = pending(c, rules)
        subs = _subs(c)
        if not alerts:
            return 0
        now = db.now_iso()
        c.executemany("INSERT OR IGNORE INTO push_sent(key, at) VALUES(?,?)", [(a["key"], now) for a in alerts])
    title, body = message(alerts)
    for s in subs:
        send(s, title, body, "/", tag="finn-alerts")
    return len(alerts)
