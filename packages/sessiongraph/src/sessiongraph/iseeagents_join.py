"""Optional join helper: SessionGraph analysis.json ↔ iseeagents provenance events.

Does not change SessionGraph Event/Session schemas. Join key is event id.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def load_iseeagents_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("schemaVersion") == "iseeagents.context.v1":
            rows.append(row)
    return rows


def join_analysis_to_provenance(
    analysis: dict[str, Any],
    provenance_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return provenance rows whose eventId appears in analysis graph/events."""
    ids: set[str] = set()
    for node in (analysis.get("graph") or {}).get("nodes") or []:
        if isinstance(node, dict) and node.get("id"):
            ids.add(str(node["id"]))
    for event in analysis.get("events") or []:
        if isinstance(event, dict) and event.get("id"):
            ids.add(str(event["id"]))
    by_id = {str(e["eventId"]): e for e in provenance_events if e.get("eventId")}
    hits: list[dict[str, Any]] = []
    for event_id in sorted(ids):
        ev = by_id.get(event_id)
        if not ev:
            continue
        hits.append(
            {
                "eventId": event_id,
                "sessionId": ev.get("sessionId"),
                "requestId": ev.get("requestId"),
                "observation": ev.get("observation"),
                "evidence": ev.get("evidence"),
                "coverage": ev.get("coverage"),
                "boundary": ev.get("boundary"),
                "adapterId": ev.get("adapterId"),
            }
        )
    return hits
