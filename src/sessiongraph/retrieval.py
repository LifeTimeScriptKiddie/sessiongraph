"""Offline adapter for CodeCollector/insane_research_standalone output.

Imports no retrieval engine and performs no network operations. URLs, page
content, error strings, headers, and summaries never enter exported events.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .model import Event, Session
from .parsers import MAX_EVENTS, MAX_TOTAL_BYTES
from .privacy import fingerprint


def load_retrieval(path: str | Path) -> Session:
    source = Path(path).expanduser().resolve()
    with source.open("rb") as handle:
        body = handle.read(MAX_TOTAL_BYTES + 1)
    if len(body) > MAX_TOTAL_BYTES:
        raise ValueError("retrieval input exceeds total byte limit")
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("engine"), dict):
        raise ValueError("expected standalone retrieval object with engine")
    engine = payload["engine"]
    trace = engine.get("trace")
    if not isinstance(trace, list) or not isinstance(engine.get("ok"), bool):
        raise ValueError("retrieval engine requires trace list and boolean ok")
    if len(trace) + 2 > MAX_EVENTS:
        raise ValueError("retrieval trace exceeds event limit")
    events = [Event("fetch", None, "retrieval_start", name="fetch")]
    elapsed = 0.0
    unsuccessful = 0
    for index, attempt in enumerate(trace, 1):
        if not isinstance(attempt, dict):
            raise ValueError("retrieval attempt must be an object")
        duration = attempt.get("elapsed_s", 0)
        try:
            valid = (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                     and math.isfinite(duration) and duration >= 0)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("attempt elapsed_s must be finite and non-negative")
        elapsed += duration
        if not math.isfinite(elapsed):
            raise ValueError("total retrieval duration exceeds numeric range")
        # A non-OK attempt is observable, but may be recovered by a later route.
        ok = attempt.get("verdict") in ("strong_ok", "weak_ok")
        unsuccessful += not ok
        event_id = f"attempt-{index}"
        events.append(Event(
            event_id, events[-1].id, "retrieval_attempt", name="attempt",
            signature=fingerprint(attempt.get("executor"), attempt.get("url_transform"),
                                  attempt.get("impersonate")),
            metadata={"elapsed_s": duration, "ok": ok},
        ))
    success = engine["ok"]
    deferred = engine.get("must_invoke_playwright_mcp") is True
    events.append(Event(
        "result", events[-1].id, "retrieval_result", name="result",
        is_error=not success,
        metadata={"ok": success, "escalation_deferred": deferred},
    ))
    return Session(source.stem, str(source), "retrieval-v1", events, metadata={
        "retrieval_attempts": len(trace), "retrieval_unsuccessful_attempts": unsuccessful,
        "retrieval_elapsed_s": elapsed, "retrieval_success": int(success),
        "retrieval_escalation_deferred": int(deferred),
    })
