"""Observe agentctl memory-plane usage exports without executing the gatekeeper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analyze import Finding
from .model import Event, Session

SCHEMA = "sessiongraph.memory_plane.v1"
_BYTE_LIMIT = 8 * 1024 * 1024


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def memory_plane_findings(metadata: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    audit_events = _nonnegative_int(metadata.get("audit_event_count", 0), "audit_event_count")
    turn_total = _nonnegative_int(metadata.get("turn_total", 0), "turn_total")
    abstain_rate = float(metadata.get("turn_abstain_rate", 0.0))
    proposed_pending = _nonnegative_int(metadata.get("proposed_pending_total", 0), "proposed_pending_total")
    accepted_total = _nonnegative_int(metadata.get("accepted_total", 0), "accepted_total")
    backend = str(metadata.get("backend") or "unknown")

    if audit_events == 0:
        findings.append(Finding(
            "no_gateway_traffic",
            "info",
            "No gatekeeper audit events in the export window",
            ["export"],
            "Confirm systemd timer window, AGENTCTL_HOME logs path, and that clients use AGENTCTL_GATEWAY_URL.",
        ))
    if turn_total >= 5 and abstain_rate >= 0.35:
        findings.append(Finding(
            "high_abstain_rate",
            "warning",
            f"Turn abstain rate is {abstain_rate:.0%} ({metadata.get('turn_abstain', 0)}/{turn_total})",
            ["turn-abstain"],
            "Seed accepted memories with provider tags, tune FTS/evidence gates, or narrow default kinds before scaling clients.",
        ))
    if proposed_pending >= 10:
        findings.append(Finding(
            "review_backlog",
            "warning",
            f"Proposed memories awaiting review: {proposed_pending}",
            ["review-queue"],
            "Add a daily operator review cadence or automate reminders via memory review queue depth alerts.",
        ))
    if turn_total >= 20 and accepted_total == 0:
        findings.append(Finding(
            "empty_memory_catalog",
            "critical",
            "Gateway traffic exists but no accepted memories are stored",
            ["store-empty"],
            "Accept baseline team memories and verify write/accept paths before expanding thin-client adoption.",
        ))
    if backend == "sqlite" and turn_total >= 200:
        findings.append(Finding(
            "postgres_migration_candidate",
            "info",
            "SQLite backend with sustained turn volume",
            ["backend-sqlite"],
            "Plan AGENTCTL_MEMORY_BACKEND=postgres on the VM when concurrent writers or HA backups are required.",
        ))
    if backend == "postgres" and turn_total < 5 and audit_events > 0:
        findings.append(Finding(
            "postgres_overprovisioned",
            "info",
            "PostgreSQL backend with low observed gatekeeper traffic",
            ["backend-postgres"],
            "Validate ops cost vs benefit; SQLite may suffice until concurrent writers or replication are needed.",
        ))
    return findings


def load_memory_plane(path: str | Path) -> Session:
    source = Path(path).resolve()
    raw = source.read_bytes()
    if len(raw) > _BYTE_LIMIT:
        raise ValueError("memory plane input exceeds total byte limit")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError(f"expected {SCHEMA} object")

    period = _require_dict(payload.get("period"), "period")
    audit = _require_dict(payload.get("audit"), "audit")
    store = _require_dict(payload.get("store"), "store")

    turn_total = _nonnegative_int(audit.get("turn_total", 0), "audit.turn_total")
    turn_abstain = _nonnegative_int(audit.get("turn_abstain", 0), "audit.turn_abstain")
    audit_event_count = _nonnegative_int(audit.get("event_count", 0), "audit.event_count")
    proposed_pending = _nonnegative_int(store.get("proposed_pending_total", 0), "store.proposed_pending_total")
    accepted_total = _nonnegative_int(store.get("accepted_total", 0), "store.accepted_total")
    backend = str(payload.get("backend") or "unknown")

    metadata: dict[str, Any] = {
        "exported_at": payload.get("exported_at"),
        "period_start": period.get("start"),
        "period_end": period.get("end"),
        "backend": backend,
        "audit_event_count": audit_event_count,
        "turn_total": turn_total,
        "turn_abstain": turn_abstain,
        "turn_abstain_rate": _rate(turn_abstain, turn_total),
        "context_total": _nonnegative_int(audit.get("context_total", 0), "audit.context_total"),
        "write_total": _nonnegative_int(audit.get("write_total", 0), "audit.write_total"),
        "accept_total": _nonnegative_int(audit.get("accept_total", 0), "audit.accept_total"),
        "unique_users": _nonnegative_int(audit.get("unique_users", 0), "audit.unique_users"),
        "workspaces_active": len(audit.get("workspaces_active") or []),
        "proposed_pending_total": proposed_pending,
        "accepted_total": accepted_total,
        "forgotten_total": _nonnegative_int(store.get("forgotten_total", 0), "store.forgotten_total"),
        "checkpoints": _nonnegative_int(store.get("checkpoints", 0), "store.checkpoints"),
        "memory_plane_success": int(
            turn_total == 0 or (turn_abstain / max(turn_total, 1)) < 0.5 and proposed_pending < 20
        ),
    }

    events: list[Event] = [
        Event("export", None, "memory_plane_export", name="export", metadata={"backend": backend}),
    ]
    routes = audit.get("routes")
    if isinstance(routes, dict):
        parent = events[-1].id
        for route, count in sorted(routes.items()):
            if not isinstance(route, str):
                continue
            events.append(Event(
                f"route-{route.strip('/') or 'root'}",
                parent,
                "audit_route",
                name=route,
                metadata={"count": _nonnegative_int(count, f"routes[{route}]")},
            ))
    if proposed_pending:
        events.append(Event(
            "review-queue",
            events[-1].id,
            "review_backlog",
            name="review",
            metadata={"pending": proposed_pending},
        ))

    session_id = source.stem or "memory-plane"
    return Session(session_id, str(source), "memory-plane-v1", events, metadata=metadata)
