"""Single entry point for model calls. Every call is logged to llm_calls."""

import os
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from backend import db
from backend.config import ROOT

load_dotenv(ROOT / ".env")

# Routing (RESEARCH E10, E14, E19):
# LITE   bulk work: classifying filings, reading filing PDFs, bios.
# SMART  Flash-Lite with the higher daily quota, for bull and bear and Ask, where Python checks every reference.
# REASON the promise ledger only: one call per company reads four transcripts and judges what happened.
LITE = os.getenv("FINN_LITE_MODEL", "gemini-3.1-flash-lite")
SMART = os.getenv("FINN_SMART_MODEL", "gemini-3.5-flash-lite")
REASON = os.getenv("FINN_REASON_MODEL", "gemini-3.6-flash")
REASON_FALLBACK = os.getenv("FINN_REASON_FALLBACK", "gemini-3.8-flash")

# When a model is out of daily quota or keeps answering 503 "high demand", try its sibling.
FALLBACK = {LITE: SMART, SMART: LITE, REASON: REASON_FALLBACK}

# Free tier limits for this project, read from AI Studio on 2026-10-31 (RESEARCH E19).
RPM = {"gemini-3.1-flash-lite": 15, "gemini-3.5-flash-lite": 15, "gemini-3.6-flash": 5, "gemini-3.8-flash": 5}
RPD = {"gemini-3.1-flash-lite": 500, "gemini-3.5-flash-lite": 500, "gemini-3.6-flash": 20, "gemini-3.8-flash": 20}
PACIFIC = ZoneInfo("America/Los_Angeles")  # "RPD quotas reset at midnight Pacific time" (Google docs)

_last_call: dict[str, float] = {}
_exhausted: dict[str, str] = {}  # model -> Pacific date on which it ran out
_rate_lock = threading.Lock()


class BudgetExhausted(Exception):
    """No model in the chain has daily quota left."""


def _pacific_day() -> str:
    return datetime.now(PACIFIC).date().isoformat()


def _used_today(model: str) -> int:
    start = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    with db.session() as c:
        return c.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE model=? AND ts >= ?",
            (model, start.isoformat(timespec="seconds")),
        ).fetchone()[0]


def has_budget(model: str) -> bool:
    if _exhausted.get(model) == _pacific_day():
        return False
    return _used_today(model) < RPD.get(model, 20)


def budget() -> dict[str, dict]:
    reset = datetime.now(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return {
        m: {"used_today": _used_today(m), "per_day": RPD[m], "per_minute": RPM[m], "exhausted": not has_budget(m)}
        for m in RPD
    } | {"_resets_at": reset.isoformat()}


def _wait_turn(model: str) -> None:
    """Space calls so a model never exceeds its per-minute limit, even across threads."""
    gap = 60.0 / RPM.get(model, 5) * 1.05
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
    retries: int = 3,
    _tried: tuple[str, ...] = (),
):
    """Returns the parsed object when `schema` is given, else text.

    Falls back to a sibling model when the chosen one is out of daily quota or overloaded.
    """
    tried = (*_tried, model)

    def fallback():
        nxt = FALLBACK.get(model)
        if nxt and nxt not in tried:
            return generate(task, nxt, contents, schema, system, _thinking_for(nxt, thinking), retries, tried)
        raise BudgetExhausted(f"no model with quota left for {task} (tried {', '.join(tried)})")

    if not has_budget(model):
        return fallback()

    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json" if schema else None,
        response_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
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
            # Say why: a per-day refusal and a per-minute one need different responses (RESEARCH E33).
            quota = ", ".join(sorted(set(re.findall(r"quotaId'?\"?:\s*'?\"?([\w-]+)", str(e))))) or "none named"
            print(f"llm: {task} on {model} refused, {e.code} ({quota}): {str(e)[:160]}", flush=True)
            if e.code == 429 and "PerDay" in str(e):
                _exhausted[model] = _pacific_day()
                return fallback()
            if e.code in (429, 500, 503) and attempt < retries - 1:
                # A ledger call sends about 160k tokens. Retrying a 503 after 5 s sent three of them inside a
                # minute and the third tripped the per-minute token limit (RELIANCE, 31 Oct). Big calls wait longer.
                big = len(str(contents)) > 200_000
                time.sleep(min(120, _retry_after(e) or (60 if big else 5) * 2**attempt))
                continue
            if e.code in (429, 500, 503):
                return fallback()
            raise


def _thinking_for(model: str, thinking: str | None) -> str | None:
    # Thinking levels are a Flash feature here; Flash-Lite calls run without one.
    return thinking if model in (REASON, REASON_FALLBACK) else None


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
