"""Single entry point for model calls. Every call is logged to llm_calls."""

import os
import re
import threading
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from backend import db
from backend.config import ROOT

load_dotenv(ROOT / ".env")

# Cheapest Gemini 3 tier for bulk text work (EVIDENCE E10). For reasoning over transcripts,
# 3.6 Flash: on the free tier 3.8 Flash took 40 s to 300 s per call and often returned 503 (E14).
LITE = os.getenv("FINN_LITE_MODEL", "gemini-3.1-flash-lite")
REASON = os.getenv("FINN_REASON_MODEL", "gemini-3.6-flash")
REASON_FALLBACK = os.getenv("FINN_REASON_FALLBACK", "gemini-3.8-flash")
# Used when a model keeps answering 503 "high demand", which happened on both Flash-Lite and 3.8 Flash.
FALLBACK = {LITE: "gemini-3.5-flash-lite", REASON: REASON_FALLBACK}

# Free tier requests per minute. 15 for 3.1 Flash-Lite is from the 429 error body (EVIDENCE E17).
RPM = {"gemini-3.1-flash-lite": 15, "gemini-3.5-flash-lite": 15, "gemini-3.6-flash": 10, "gemini-3.8-flash": 10}
_last_call: dict[str, float] = {}
_rate_lock = threading.Lock()


def _wait_turn(model: str) -> None:
    """Space calls so a model never exceeds its per-minute limit, even across threads."""
    gap = 60.0 / RPM.get(model, 10) * 1.05
    with _rate_lock:
        now = time.time()
        start = max(now, _last_call.get(model, 0) + gap)
        _last_call[model] = start
    if start > now:
        time.sleep(start - now)


def _retry_after(e: errors.APIError) -> float | None:
    m = re.search(r"retry in ([\d.]+)s", str(e))
    return float(m.group(1)) + 1 if m else None


_client: genai.Client | None = None
_client_lock = threading.Lock()


def client() -> genai.Client:
    # One shared client. Without the lock, parallel threads each build one and the losers get
    # garbage-collected mid-request ("Cannot send a request, as the client has been closed").
    global _client
    with _client_lock:
        if _client is None:
            _client = genai.Client()
    return _client


def generate(
    task: str,
    model: str,
    contents,
    schema=None,
    system: str | None = None,
    thinking: str | None = None,
    cached_content: str | None = None,
    retries: int = 4,
):
    """Returns the parsed object when `schema` is given, else text."""
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json" if schema else None,
        response_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
        cached_content=cached_content,
    )
    for attempt in range(retries):
        _wait_turn(model)
        t0 = time.time()
        try:
            r = client().models.generate_content(model=model, contents=contents, config=cfg)
            _log(task, model, r.usage_metadata, t0, ok=True)
            return r.parsed if schema else r.text
        except errors.APIError as e:
            _log(task, model, None, t0, ok=False)
            if e.code in (429, 500, 503) and attempt < retries - 1:
                time.sleep(min(90, _retry_after(e) or 5 * 2**attempt))
                continue
            if e.code in (500, 503) and model in FALLBACK:
                return generate(task, FALLBACK[model], contents, schema, system, thinking, cached_content, retries=2)
            raise


def _log(task: str, model: str, usage, t0: float, ok: bool) -> None:
    u = usage
    with db.session() as c:
        c.execute(
            "INSERT INTO llm_calls(task, model, tokens_in, tokens_out, tokens_cached, tokens_thinking,"
            " latency_ms, ok, ts) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                task,
                model,
                getattr(u, "prompt_token_count", None),
                getattr(u, "candidates_token_count", None),
                getattr(u, "cached_content_token_count", None),
                getattr(u, "thoughts_token_count", None),
                int((time.time() - t0) * 1000),
                int(ok),
                db.now_iso(),
            ),
        )
