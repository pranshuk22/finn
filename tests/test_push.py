"""Which alerts reach the phone, and that each is sent once."""

from datetime import UTC, datetime

import pytest


@pytest.fixture
def c(tmp_path, monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db", raising=False)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db", raising=False)
    db.init()
    with db.session() as conn:
        yield conn


def filing(c, id_, ticker, at, priority, category, summary="x"):
    c.execute(
        "INSERT INTO filings(id, ticker, an_dt, priority, category, summary) VALUES(?,?,?,?,?,?)",
        (id_, ticker, at, priority, category, summary),
    )


NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)  # 17:30 IST


def test_new_filings_that_need_you_or_are_flagged(c):
    from backend import push

    filing(c, "1", "DIXON", "2026-10-30T16:07:00", "needs_you", "results", "Q2 FY27 results")
    filing(c, "2", "TCS", "2026-10-30T16:30:00", "worth_knowing", "M&A", "Acquires a firm")
    filing(c, "3", "TCS", "2026-10-30T16:40:00", "worth_knowing", "dividend", "Record date")
    filing(c, "4", "INFY", "2026-10-30T09:00:00", "needs_you", "results", "Old news")  # before the 3 hours
    got = push.pending(c, {"categories": ["M&A"]}, now=NOW)
    assert [a["key"] for a in got] == ["filing:1", "filing:2"]
    c.executemany("INSERT INTO push_sent(key, at) VALUES(?, 'x')", [(a["key"],) for a in got])
    assert push.pending(c, {"categories": ["M&A"]}, now=NOW) == []  # sent once


def test_message_names_the_rest_by_ticker():
    from backend import push

    alerts = [{"ticker": t, "line": f"{t}: filed"} for t in ["A", "B", "C", "D", "E", "D"]]
    title, body = push.message(alerts)
    assert title == "6 FINN alerts"
    assert body.splitlines() == ["A: filed", "B: filed", "C: filed", "Also: D, E"]
    assert push.message(alerts[:1]) == ("FINN alert", "A: filed")


def test_public_key_is_an_uncompressed_p256_point(tmp_path, monkeypatch):
    import base64

    from backend import push

    monkeypatch.setattr(push, "KEY_PATH", tmp_path / "k.pem")
    raw = base64.urlsafe_b64decode(push.public_key() + "=")
    assert len(raw) == 65 and raw[0] == 4
    assert push.public_key() == push.public_key()  # one key, kept


def test_message_is_encrypted_for_the_phone_and_signed_by_the_server(tmp_path, monkeypatch):
    """What a push service receives: a body only the subscriber can decrypt (RFC 8291) and a VAPID token signed
    with the server's key (RFC 8292). Checked against a local endpoint standing in for Google's or Apple's."""
    import base64
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import http_ece
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    from backend import push

    monkeypatch.setattr(push, "KEY_PATH", tmp_path / "k.pem")
    got = {}

    class Endpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            got["headers"] = dict(self.headers)
            got["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Endpoint)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    phone = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    point = phone.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    sub = {
        "endpoint": f"http://127.0.0.1:{srv.server_port}/push/abc",
        "keys": {"p256dh": b64(point), "auth": b64(auth)},
    }
    assert push.send(sub, "FINN alert", "DIXON: Q2 FY27 results", "/")

    msg = json.loads(http_ece.decrypt(got["body"], private_key=phone, auth_secret=auth, version="aes128gcm"))
    assert msg["title"] == "FINN alert" and msg["body"] == "DIXON: Q2 FY27 results"

    headers = {k.lower(): v for k, v in got["headers"].items()}
    assert headers["content-encoding"] == "aes128gcm" and headers["ttl"] == str(12 * 3600)
    scheme, params = headers["authorization"].split(" ", 1)
    parts = dict(p.strip().split("=", 1) for p in params.split(","))
    assert parts["k"] == push.public_key()  # the key the browser subscribed with
    token = parts["t"]
    head, payload, sig = token.split(".")
    unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    r, s_ = int.from_bytes(unb64(sig)[:32], "big"), int.from_bytes(unb64(sig)[32:], "big")
    server_pub = serialization.load_pem_private_key(push.KEY_PATH.read_bytes(), None).public_key()
    # raises if the token was not signed with the server's key
    server_pub.verify(encode_dss_signature(r, s_), f"{head}.{payload}".encode(), ec.ECDSA(hashes.SHA256()))
    claims = json.loads(unb64(payload))
    assert scheme == "vapid" and claims["sub"] == push.CLAIMS["sub"]
    assert claims["aud"] == f"http://127.0.0.1:{srv.server_port}"
