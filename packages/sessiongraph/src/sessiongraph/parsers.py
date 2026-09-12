from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

from .model import Event, Session
from .privacy import fingerprint, redact, sanitize


MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 100_000
AGENTCTL_LOOP_EVENTS = {"generate", "validate", "evaluate", "decision", "finish"}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return ""


def _usage(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    usage: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            number = float(value)
        except OverflowError as exc:
            raise ValueError(f"usage value for {key!r} is out of range") from exc
        if not math.isfinite(number):
            raise ValueError(f"usage value for {key!r} must be finite")
        usage[str(key)] = number
    return usage


def _require_unique_ids(events: list[Event], source: Path) -> None:
    seen: set[str] = set()
    for event in events:
        if event.id in seen:
            raise ValueError(f"{source}: duplicate event id {event.id!r}")
        seen.add(event.id)


def _append_event(events: list[Event], event: Event, source: Path) -> None:
    if len(events) >= MAX_EVENTS:
        raise ValueError(f"{source}: exceeds {MAX_EVENTS} events")
    events.append(event)


def parse_pi(lines: list[dict[str, Any]], source: Path) -> Session:
    header = lines[0]
    events: list[Event] = []
    for index, entry in enumerate(lines[1:], 1):
        entry_id = str(entry.get("id") or f"entry-{index}")
        parent_id = str(entry["parentId"]) if entry.get("parentId") is not None else None
        if entry.get("type") != "message":
            _append_event(events, Event(
                id=entry_id, parent_id=parent_id, kind=str(entry.get("type", "event")),
                timestamp=entry.get("timestamp"), signature=fingerprint(entry.get("type"), entry.get("modelId")),
            ), source)
            continue

        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        role = str(message.get("role", "unknown"))
        content = message.get("content", [])
        text = _text(content)
        safe_text, labels = redact(text)
        name = message.get("toolName")
        kind = "message"
        if role == "toolResult":
            kind, name = "tool_result", message.get("toolName")
            tool_parent = message.get("toolCallId") or parent_id
            parent_id = str(tool_parent) if tool_parent else None
        elif role == "bashExecution":
            kind, name = "tool_result", "bash"
            safe_text, labels = redact(str(message.get("output", "")))
        event = Event(
            id=entry_id, parent_id=parent_id, kind=kind, role=role, name=str(name) if name else None,
            timestamp=entry.get("timestamp") or message.get("timestamp"), text=safe_text,
            signature=fingerprint(kind, role, name, safe_text),
            is_error=bool(message.get("isError")) or message.get("stopReason") in {"error", "aborted"},
            usage=_usage(message.get("usage")),
            metadata={"redactions": labels, "stop_reason": message.get("stopReason")},
        )
        _append_event(events, event, source)

        if isinstance(content, list):
            for content_index, item in enumerate(content):
                if not isinstance(item, dict) or item.get("type") != "toolCall":
                    continue
                tool_id = str(item.get("id") or f"{entry_id}-tool-{content_index}")
                args = item.get("arguments", {})
                safe_args, arg_labels = sanitize(args)
                args_text = json.dumps(safe_args, sort_keys=True, default=str)
                _append_event(events, Event(
                    id=tool_id, parent_id=entry_id, kind="tool_call", role="assistant",
                    name=str(item.get("name", "unknown")), timestamp=event.timestamp,
                    text=args_text, signature=fingerprint("tool_call", item.get("name"), safe_args),
                    metadata={"redactions": arg_labels},
                ), source)
    _require_unique_ids(events, source)
    return Session(
        id=str(header.get("id") or source.stem), source=str(source), format="pi-v3",
        events=events, metadata={
            "cwd_fingerprint": fingerprint("cwd", header.get("cwd")) if header.get("cwd") else None,
            "version": header.get("version"),
        },
    )


def parse_generic(lines: list[dict[str, Any]], source: Path) -> Session:
    events: list[Event] = []
    previous: str | None = None
    for index, raw in enumerate(lines):
        event_id = str(raw.get("id") or f"event-{index + 1}")
        role = raw.get("role")
        kind = str(raw.get("kind") or raw.get("type") or "message")
        name = raw.get("name") or raw.get("tool") or raw.get("tool_name")
        text = _text(raw.get("content", raw.get("text", "")))
        safe_text, labels = redact(text)
        is_error = bool(raw.get("is_error") or raw.get("error"))
        parents = None
        if "parent_ids" in raw:
            parents = raw["parent_ids"]
            if (not isinstance(parents, list) or len(parents) > 1024
                    or any(not isinstance(p, str) or not p for p in parents)
                    or len(parents) != len(set(parents))):
                raise ValueError(f"{source}: parent_ids must be a unique list of at most 1024 nonempty IDs")
            if raw.get("parent_id") is not None and (not parents or raw["parent_id"] != parents[0]):
                raise ValueError(f"{source}: parent_id must match the first parent_ids entry")
            parent_id = parents[0] if parents else None
        elif "parent_id" in raw:
            # Explicit null declares a root. Only omitted lineage gets legacy order fallback.
            parent_id = str(raw["parent_id"]) if raw["parent_id"] is not None else None
        else:
            parent_id = previous
        parent_relations = raw.get("parent_relations", {})
        if not isinstance(parent_relations, dict):
            raise ValueError(f"{source}: parent_relations must be an object")
        declared_parents = parents if parents is not None else ([parent_id] if parent_id else [])
        if (any(not isinstance(key, str) or key not in declared_parents for key in parent_relations)
                or any(not isinstance(value, str) or not value.strip() or len(value) > 64
                       for value in parent_relations.values())):
            raise ValueError(
                f"{source}: parent_relations must map declared parent IDs to nonempty strings of at most 64 characters"
            )
        _append_event(events, Event(
            id=event_id, parent_id=parent_id,
            kind=kind, role=str(role) if role else None, name=str(name) if name else None,
            timestamp=raw.get("timestamp"), text=safe_text,
            signature=fingerprint(kind, role, name, sanitize(raw.get("arguments", safe_text))[0]),
            is_error=is_error, usage=_usage(raw.get("usage")), metadata={"redactions": labels,
                **({"parent_ids": list(parents)} if parents is not None else {}),
                **({"parent_relations": dict(parent_relations)} if parent_relations else {})},
        ), source)
        previous = event_id
    _require_unique_ids(events, source)
    return Session(id=source.stem, source=str(source), format="generic-jsonl", events=events)


def parse_agentctl_loop(lines: list[dict[str, Any]], source: Path) -> Session:
    """Parse agentctl's redacted improvement-loop trace into an unrolled state graph."""
    events: list[Event] = []
    previous: str | None = None
    adapters: set[str] = set()
    final_status: str | None = None
    max_iteration = 0
    allowed_metadata = {
        "adapter", "ok", "failureClass", "durationMs", "candidateHash", "passed",
        "checks", "action", "reason", "score", "dryRun", "status",
    }
    for index, raw in enumerate(lines, 1):
        event_name = raw.get("event")
        iteration = raw.get("iteration")
        if event_name not in AGENTCTL_LOOP_EVENTS or isinstance(iteration, bool) or not isinstance(iteration, int):
            raise ValueError(f"{source}:{index}: malformed agentctl loop event")
        if iteration < 0:
            raise ValueError(f"{source}:{index}: agentctl iteration must be non-negative")
        max_iteration = max(max_iteration, iteration)
        event_id = f"iteration-{iteration:03d}-{event_name}-{index:04d}"
        selected = {key: raw[key] for key in allowed_metadata if key in raw}
        safe_metadata, labels = sanitize(selected)
        safe_metadata.update({"event": event_name, "iteration": iteration, "redactions": labels})
        adapter = raw.get("adapter")
        if isinstance(adapter, str):
            adapters.add(adapter)
        if event_name == "finish" and isinstance(raw.get("status"), str):
            final_status = raw["status"]
        failed = (
            event_name in {"generate", "evaluate"} and raw.get("ok") is False
        ) or (
            event_name == "finish" and raw.get("status") in {"failed", "stopped"}
        )
        event = Event(
            id=event_id,
            parent_id=previous,
            kind=f"loop_{event_name}",
            role="controller",
            name=adapter if isinstance(adapter, str) else str(event_name),
            timestamp=raw.get("ts"),
            signature=fingerprint(
                "agentctl-loop", event_name, adapter, raw.get("action"),
                raw.get("status"), raw.get("failureClass"),
            ),
            is_error=failed,
            metadata=safe_metadata,
        )
        _append_event(events, event, source)
        previous = event_id
    return Session(
        id=source.parent.name or source.stem,
        source=str(source),
        format="agentctl-loop-v1",
        events=events,
        metadata={
            "iterations": max_iteration,
            "status": final_status,
            "adapters": sorted(adapters),
        },
    )


def load_session(path: str | Path) -> Session:
    source = Path(path).expanduser().resolve()
    lines: list[dict[str, Any]] = []
    with source.open("rb") as handle:
        number = 0
        total_bytes = 0
        while True:
            raw_line = handle.readline(MAX_LINE_BYTES + 1)
            if not raw_line:
                break
            number += 1
            total_bytes += len(raw_line)
            if len(raw_line) > MAX_LINE_BYTES:
                raise ValueError(f"{source}:{number}: line exceeds {MAX_LINE_BYTES} bytes")
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError(f"{source}: exceeds {MAX_TOTAL_BYTES} total bytes")
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"{source}:{number}: invalid UTF-8") from exc
            if not line.strip():
                continue
            if len(lines) >= MAX_EVENTS:
                raise ValueError(f"{source}: exceeds {MAX_EVENTS} events")
            try:
                value = json.loads(
                    line,
                    parse_constant=lambda constant: (_ for _ in ()).throw(
                        ValueError(f"non-standard numeric constant {constant}")
                    ),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                message = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
                raise ValueError(f"{source}:{number}: invalid JSON: {message}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{source}:{number}: expected a JSON object")
            lines.append(value)
    if not lines:
        raise ValueError(f"{source}: empty session")
    if lines[0].get("event") in AGENTCTL_LOOP_EVENTS and "iteration" in lines[0]:
        return parse_agentctl_loop(lines, source)
    if lines[0].get("type") == "session" and "version" in lines[0]:
        return parse_pi(lines, source)
    return parse_generic(lines, source)


def discover_pi_sessions(root: str | Path | None = None) -> Iterable[Path]:
    base = Path(root).expanduser() if root else Path.home() / ".pi" / "agent" / "sessions"
    if base.exists():
        yield from sorted(base.rglob("*.jsonl"))
