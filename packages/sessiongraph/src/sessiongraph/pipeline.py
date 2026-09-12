"""Observe externally verified pipeline artifacts without executing their producer.

Verdicts are supplied by a verifier, not inferred from prose or process success.
Fixture/verifier/contract digests permit matched comparisons, not proof of truth.
Absolute input paths, commands, stage names and arbitrary content are not exported.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from .model import Event, Session
from .parsers import MAX_EVENTS, MAX_TOTAL_BYTES
from .privacy import fingerprint


def _identifier(value):
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError("pipeline identifiers must be nonempty strings of at most 200 characters")
    return value


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("pipeline digests must be lowercase SHA256 hex strings")
    return value


def load_pipeline(path: str | Path) -> Session:
    source = Path(path).expanduser().resolve()
    with source.open("rb") as handle:
        body = handle.read(MAX_TOTAL_BYTES + 1)
    if len(body) > MAX_TOTAL_BYTES:
        raise ValueError("pipeline input exceeds total byte limit")
    payload = json.loads(body)
    if not isinstance(payload, dict) or payload.get("schema") != "sessiongraph.pipeline.v1":
        raise ValueError("expected sessiongraph.pipeline.v1 object")
    fixture = _digest(payload.get("fixture_sha256"))
    verifier = _digest(payload.get("verifier_sha256"))
    revision = _digest(payload["source_sha256"]) if "source_sha256" in payload else None
    required = payload.get("required_stages")
    checks = payload.get("required_checks")
    stages = payload.get("stages")
    if not isinstance(required, list) or not required or not isinstance(checks, dict) or not checks:
        raise ValueError("pipeline requires nonempty required_stages and required_checks")
    required = [_identifier(item) for item in required]
    if len(set(required)) != len(required):
        raise ValueError("duplicate required pipeline stage")
    stage_positions = {name: index for index, name in enumerate(required)}
    for key, value in checks.items():
        _identifier(key)
        if _identifier(value) not in stage_positions:
            raise ValueError("required check must belong to a required stage")
    if not isinstance(stages, list) or len(required) + len(checks) + 2 > MAX_EVENTS:
        raise ValueError("invalid pipeline stage list or event limit exceeded")
    contract = hashlib.sha256(json.dumps(
        {"stages": required, "checks": checks}, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    stage_ids = {key: f"stage-{index}" for index, key in enumerate(required, 1)}
    check_ids = {key: f"check-{index}" for index, key in enumerate(sorted(checks), 1)}
    events = [Event("run", None, "pipeline_start", name="run")]
    seen_stages, seen_checks = set(), set()
    passed = failed = completed = timeouts = 0
    durations = {}
    last_index = -1
    for stage in stages:
        if not isinstance(stage, dict):
            raise ValueError("pipeline stage must be an object")
        name = _identifier(stage.get("id"))
        if name not in stage_ids or name in seen_stages:
            raise ValueError("unknown or duplicate pipeline stage")
        index = stage_positions[name]
        if index <= last_index:
            raise ValueError("pipeline stages must follow declared execution order")
        last_index = index
        seen_stages.add(name)
        status = stage.get("status")
        if not isinstance(status, str) or status not in {"completed", "failed", "blocked", "timeout"}:
            raise ValueError("invalid pipeline stage status")
        duration = stage.get("duration_ms")
        try:
            valid = (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                     and math.isfinite(duration) and duration >= 0)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("pipeline duration_ms must be finite and non-negative")
        event_id = stage_ids[name]
        durations[event_id] = duration
        completed += status == "completed"
        timeouts += status == "timeout"
        events.append(Event(event_id, events[-1].id, "pipeline_stage", name=event_id,
                            signature=fingerprint(name), is_error=status != "completed",
                            metadata={"status": status, "duration_ms": duration}))
        results = stage.get("checks", [])
        if not isinstance(results, list):
            raise ValueError("pipeline checks must be a list")
        for check in results:
            if not isinstance(check, dict):
                raise ValueError("pipeline check must be an object")
            key = _identifier(check.get("id"))
            if checks.get(key) != name or key in seen_checks:
                raise ValueError("unknown, misplaced or duplicate pipeline check")
            seen_checks.add(key)
            ok = check.get("passed")
            if type(ok) is not bool:
                raise ValueError("pipeline check passed must be boolean")
            evidence = _digest(check.get("evidence_sha256"))
            passed += ok
            failed += not ok
            events.append(Event(check_ids[key], event_id, "pipeline_check", name=check_ids[key],
                                signature=fingerprint(key), is_error=not ok,
                                metadata={"passed": ok, "evidence_sha256": evidence}))
    try:
        elapsed = sum(durations.values())
        valid_total = math.isfinite(elapsed)
    except OverflowError:
        valid_total = False
    if not valid_total:
        raise ValueError("total pipeline duration exceeds numeric range")
    missing_checks = len(checks) - len(seen_checks)
    missing_stages = len(required) - len(seen_stages)
    success = completed == len(required) and passed == len(checks)
    events.append(Event("result", events[-1].id, "pipeline_result", name="result", is_error=not success,
                        metadata={"reported_verification_success": success,
                                  "missing_checks": missing_checks, "missing_stages": missing_stages}))
    return Session(source.stem, str(source), "pipeline-v1", events, metadata={
        "fixture_sha256": fixture, "verifier_sha256": verifier, "contract_sha256": contract,
        "source_sha256": revision, "pipeline_stages_required": len(required),
        "pipeline_stages_completed": completed, "pipeline_stages_missing": missing_stages,
        "pipeline_checks_required": len(checks), "pipeline_checks_passed": passed,
        "pipeline_checks_failed": failed, "pipeline_checks_missing": missing_checks,
        "pipeline_timeouts": timeouts, "pipeline_duration_ms": elapsed,
        "pipeline_stage_duration_ms": durations, "pipeline_success": int(success),
    })
