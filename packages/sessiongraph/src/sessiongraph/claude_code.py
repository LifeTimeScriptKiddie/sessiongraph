"""The one Claude Code transcript reader every command uses.

It turns ~/.claude/projects/**/<session>.jsonl into a Session of generic events:

- message (role user): a typed turn. metadata: author, author_reason, command,
  wrapper (text starts with "<"), meta (isMeta: injected mid-request, such as skill text)
- interrupt: "[Request interrupted by user]"
- message (role assistant): one per assistant record. metadata: model, output_tokens
  (new tokens only; Claude Code repeats a message's usage on every content block)
- tool_call: id = tool_use id. metadata: phase, skill. text: the command or main argument
- tool_result: parent_id = its tool_call. metadata: denial (toolDenialKind). text: start of the output
- subagent events: a linked subagent transcript's events, under the tool call that started it.
  metadata: subagent = agentId

Commands decide which turns start a request (see `segment`), so each keeps its own
semantics while counting the same events. Text is held in memory for detectors and
display only: Event.public() drops it unless content is explicitly requested, and no
content goes into metadata.

The transcript format is internal to Claude Code and may change; the reader relies
only on the fields named here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .model import Event, Session
from .privacy import fingerprint, sanitize
from .workflows import _BORING_COMMANDS, _COMMAND, _ts, phase_of

READER = "claude-code-v1"
INTERRUPT = re.compile(r"\[Request interrupted by user")
COMPACTION = "This session is being continued from a previous conversation"
_ARG_KEYS = ("command", "file_path", "pattern", "url", "query", "skill", "description", "prompt")


def author_of(rec: dict[str, Any], text: str) -> tuple[str, str]:
    """Who wrote a user-role turn, from recorded fields only. Unmarked turns stay unknown."""
    origin = rec.get("origin") if isinstance(rec.get("origin"), dict) else {}
    kind, source = origin.get("kind"), rec.get("promptSource")
    if rec.get("isMeta"):
        return "system", "isMeta"
    if rec.get("entrypoint") == "sdk-cli" or source == "sdk":
        return "agent", "sdk prompt (headless run, e.g. agentctl)"
    if kind == "peer":
        return "agent", "peer session message"
    if kind in {"task-notification", "auto-continuation"} or source == "system":
        return "system", f"origin {kind or source}"
    if kind == "human" or source in {"typed", "queued"} or rec.get("turnOrigin") == "human":
        return "human", "origin human"
    if text.startswith(COMPACTION):
        return "system", "compaction summary"
    return "unknown", "no origin marker"


def turn_text(content: Any) -> str | None:
    """A user record's text, when it is text and not tool results."""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and all(
            isinstance(b, dict) and b.get("type") == "text" for b in content):
        return "\n".join(str(b.get("text", "")) for b in content)
    return None


def _argument(tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in _ARG_KEYS:
            if isinstance(tool_input.get(key), str):
                return tool_input[key]
    return ""


def _records(path: Path) -> Iterable[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            yield rec


def _read_events(path: Path, since: datetime | None, prefix: str = "") -> tuple[list[Event], dict[str, str]]:
    """Events of one transcript, plus {agentId: tool_use id} for subagents it started."""
    events: list[Event] = []
    seen_usage: dict[str, int] = {}
    started: dict[str, str] = {}

    def add(event: Event) -> None:
        if event.parent_id is None and events:
            event.parent_id = events[-1].id
        events.append(event)

    for index, rec in enumerate(_records(path)):
        ts = rec.get("timestamp")
        parsed = _ts(ts)
        if since and parsed and parsed < since:
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        content = msg.get("content")
        rid = prefix + str(rec.get("uuid") or f"line-{index}")
        kind = rec.get("type")
        if kind == "assistant":
            mid = msg.get("id")
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            out = usage.get("output_tokens")
            new_tokens = 0
            if isinstance(out, int) and mid:
                new_tokens = max(0, out - seen_usage.get(mid, 0))
                seen_usage[mid] = max(out, seen_usage.get(mid, 0))
            model = msg.get("model") if isinstance(msg.get("model"), str) and not msg["model"].startswith("<") else None
            add(Event(rid, None, "message", role="assistant", timestamp=ts,
                      metadata={"model": model, "output_tokens": new_tokens}))
            for block in content or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = str(block.get("name", "unknown"))
                tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                safe_args, _ = sanitize(tool_input)
                skill = tool_input.get("skill") if name == "Skill" else None
                add(Event(prefix + str(block.get("id")), rid, "tool_call", role="assistant", name=name,
                          timestamp=ts, text=_argument(tool_input),
                          signature=fingerprint("tool_call", name, safe_args),
                          metadata={"phase": phase_of(name, tool_input),
                                    "skill": skill if isinstance(skill, str) and re.fullmatch(r"[\w:.-]{1,60}", skill)
                                    else None}))
            continue
        if kind != "user":
            continue
        text = turn_text(content)
        if text is not None:
            stripped = text.strip()
            if INTERRUPT.match(stripped):
                add(Event(rid, None, "interrupt", role="user", timestamp=ts))
                continue
            command = _COMMAND.search(text)
            author, reason = author_of(rec, stripped)
            add(Event(rid, None, "message", role="user", timestamp=ts, text=stripped, metadata={
                "author": author, "author_reason": reason, "meta": bool(rec.get("isMeta")),
                "wrapper": stripped.startswith("<"), "command": command.group(1) if command else None,
                "string_content": isinstance(content, str),
                "cwd": rec.get("cwd") if isinstance(rec.get("cwd"), str) else None,
                "git_branch": rec.get("gitBranch") if isinstance(rec.get("gitBranch"), str) else None}))
            continue
        if isinstance(content, list):
            result = rec.get("toolUseResult")
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                call_id = prefix + str(block.get("tool_use_id"))
                body = block.get("content")
                body = body if isinstance(body, str) else json.dumps(body, default=str)
                add(Event(f"r-{call_id}", call_id, "tool_result", timestamp=ts, text=body[:500],
                          is_error=bool(block.get("is_error")),
                          metadata={"denial": rec.get("toolDenialKind")}))
                if isinstance(result, dict) and isinstance(result.get("agentId"), str):
                    started[result["agentId"]] = call_id
    return events, started


def read_transcript(path: str | Path, since: datetime | None = None, subagents: bool = True) -> Session:
    """One transcript as a Session; linked subagent transcripts become child events."""
    source = Path(path)
    events, started = _read_events(source, since)
    linked, unlinked = 0, 0
    folder = source.with_suffix("") / "subagents"
    if subagents and folder.is_dir():
        for sub in sorted(folder.glob("agent-*.jsonl")):
            agent_id = sub.stem.removeprefix("agent-")
            if agent_id not in started:
                unlinked += 1  # started by a local command, not a tool call: no parent to attach to
                continue
            sub_events, _ = _read_events(sub, since, prefix=f"sa-{agent_id}-")
            if sub_events:
                sub_events[0].parent_id = started[agent_id]
            for event in sub_events:
                event.metadata["subagent"] = agent_id
            events.extend(sub_events)
            linked += 1
    return Session(source.stem, str(source), "claude-code-v1", events, metadata={
        "reader": READER, "subagents_linked": linked, "subagents_unlinked": unlinked})


def transcripts(root: str | Path) -> list[Path]:
    """Main transcripts under a Claude Code projects root; subagent files are read through their parent."""
    return [p for p in sorted(Path(root).expanduser().glob("**/*.jsonl")) if "subagents" not in p.parts]


def is_claude_code(first_records: list[dict[str, Any]]) -> bool:
    return any(isinstance(r, dict) and "sessionId" in r and r.get("type") in {"user", "assistant", "system"}
               for r in first_records)


@dataclass(slots=True)
class Segment:
    """A turn that starts a request, and the events that follow it until the next such turn."""
    turn: Event
    events: list[Event] = field(default_factory=list)

    @property
    def calls(self) -> list[Event]:
        return [e for e in self.events if e.kind == "tool_call"]


def segment(session: Session, starts: Callable[[Event], bool]) -> list[Segment]:
    """Split the parent transcript's events into requests. Events before the first start are dropped.

    Subagent events are left out: commands judge the session the human or caller drove.
    """
    out: list[Segment] = []
    for event in session.events:
        if event.metadata.get("subagent"):
            continue
        if event.kind == "message" and event.role == "user" and starts(event):
            out.append(Segment(event))
        elif out:
            out[-1].events.append(event)
    return out


def is_boring(event: Event) -> bool:
    return event.metadata.get("command") in _BORING_COMMANDS
