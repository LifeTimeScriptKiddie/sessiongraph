"""Read ~/.agentctl job store under the S2 privacy allow-list (content-free)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .failure_tags import KNOWN_FAILURE_CLASSES, classify_agentctl, scan_json_blob

# Top-level + nested ask.* keys SessionGraph may retain. Everything else is dropped.
ALLOW_TOP = frozenset({
    "id", "kind", "status", "created", "created_at", "finished", "finished_at",
    "agent", "model", "effort", "failureClass", "tags", "refusal", "steppedDown",
    "role", "policy_remap", "plan_ref", "needs", "usage", "ask",
})
ALLOW_ASK = frozenset({
    "agent", "model", "ok", "failureClass", "steppedDown", "usage", "costUsd",
    "sessionId", "tags", "refusal", "role", "needs", "policy_remap", "plan_ref",
    # evidence is parse-and-drop only — never retained in the allow-listed record
})
DENY_FILES = frozenset({"input.json", "route-log.jsonl"})


def agentctl_home(path: str | Path | None = None) -> Path:
    return Path(path).expanduser() if path else Path.home() / ".agentctl"


def _pick(src: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    return {k: src[k] for k in allowed if k in src}


def project_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Drop deny-listed bodies; keep only allow-listed keys. Parse evidence for refusal then discard it."""
    out = _pick(raw, ALLOW_TOP - {"ask"})
    ask_raw = raw.get("ask")
    if isinstance(ask_raw, dict):
        ask = _pick(ask_raw, ALLOW_ASK)
        # Parse-and-drop: structured refusal from evidence, never keep the blob.
        if "refusal" not in ask and isinstance(ask_raw.get("evidence"), str):
            found = scan_json_blob(ask_raw["evidence"])
            if found:
                ask["refusal"] = found
        # Fixed phrase on ask.text for legacy detection, without retaining full text.
        text = ask_raw.get("text")
        if isinstance(text, str) and text:
            from .failure_tags import refusal_from_ask_text

            phrase = refusal_from_ask_text(text)
            if phrase and "refusal" not in ask:
                ask["refusal"] = phrase
            # Keep only a content-free flag that a safeguard phrase was present.
            if phrase:
                ask["safeguard_phrase"] = True
        out["ask"] = ask
    # Never copy stdout / normalizedText even if present on a merged blob.
    return out


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iter_jobs(
    home: str | Path | None = None,
    *,
    since: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield allow-listed job records from job.json + result.json (never input.json)."""
    root = agentctl_home(home) / "jobs"
    if not root.is_dir():
        return
    for job_dir in sorted(root.iterdir()):
        if not job_dir.is_dir():
            continue
        # Hard deny: never open these files.
        for denied in DENY_FILES:
            if (job_dir / denied).exists():
                pass  # existence is fine; we simply never read them
        job = _read_json(job_dir / "job.json") or {}
        result = _read_json(job_dir / "result.json") or {}
        if not job and not result:
            continue
        merged: dict[str, Any] = {**job, **result}
        if "id" not in merged:
            merged["id"] = job_dir.name
        finished = (
            _parse_ts(merged.get("finished_at"))
            or _parse_ts(merged.get("finished"))
            or _parse_ts(merged.get("created_at"))
            or _parse_ts(merged.get("created"))
        )
        if since and finished and finished < since:
            continue
        if since and not finished:
            # No timestamp: include (better false-positive than silent drop for MVP).
            pass
        projected = project_record(merged)
        projected["id"] = str(merged.get("id") or job_dir.name)
        if finished:
            projected["finished_at"] = finished.isoformat()
        yield projected


def iter_policy_remaps(home: str | Path | None = None) -> Iterator[dict[str, Any]]:
    path = agentctl_home(home) / "policy-remaps.jsonl"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            # Content-free remap fields only.
            yield {
                k: rec[k]
                for k in (
                    "ts", "job_id", "task_id", "surface", "requested", "applied",
                    "rule", "remapped", "model_dropped",
                )
                if k in rec
            }


def enrich_with_remaps(records: list[dict[str, Any]], home: str | Path | None = None) -> list[dict[str, Any]]:
    remaps = list(iter_policy_remaps(home))
    by_job = {str(r.get("job_id")): r for r in remaps if r.get("job_id")}
    out: list[dict[str, Any]] = []
    for rec in records:
        copy = dict(rec)
        rid = str(copy.get("id") or "")
        if rid in by_job:
            copy["policy_remap"] = by_job[rid]
        out.append(copy)
    return out


def classify_jobs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    for rec in records:
        tags = classify_agentctl(rec)
        ask = rec.get("ask") if isinstance(rec.get("ask"), dict) else {}
        fc = ask.get("failureClass", rec.get("failureClass"))
        classified.append({
            "id": rec.get("id"),
            "kind": rec.get("kind"),
            "agent": ask.get("agent", rec.get("agent")),
            "model": ask.get("model", rec.get("model")),
            "role": ask.get("role", rec.get("role")),
            "failureClass": fc,
            "tags": tags,
            "legacy_relabel": "legacy_relabel" in tags,
            "finished_at": rec.get("finished_at"),
        })
    return classified


def unknown_failure_classes(classified: list[dict[str, Any]]) -> list[str]:
    unknown: list[str] = []
    for row in classified:
        fc = row.get("failureClass")
        if isinstance(fc, str) and fc and fc not in KNOWN_FAILURE_CLASSES:
            unknown.append(fc)
    return sorted(set(unknown))
