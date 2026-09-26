"""Cross-session workflow mining (content-free).

A *request* is one user turn and everything the agent did for it. Each request
is reduced to a sequence of coarse phases (explore, edit, test, build, commit,
delegate, web, shell, skill) plus an optional anchor (the slash command or
skill that started it). Raw tool names are too fine-grained to reveal repeated
workflows; phases are not.

Requests are grouped into workflow *families* (lookup, edit, edit-test, ship,
delegate, ... or the anchor), and for each family we build a directly-follows
graph (DFG) over phases and count its *variants* (distinct phase shapes). The
worth-it gate (worth_it.py) then decides, per family, whether to observe only,
apply a cheap fix, or engineer the workflow.

Privacy: readers keep tool names, phase labels, counts, token usage, error
flags, timestamps and model ids. Prompt text, tool arguments, file paths,
commands and answers are read only to classify a phase and are never stored.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

SCHEMA = "sessiongraph.workflows.v1"
PHASES = ("explore", "edit", "test", "build", "commit", "delegate", "subagent", "web", "skill", "shell")
MAX_SHAPE = 8
# phases whose failures are the point (a red test tells the agent what to fix)
EXPECTED_FAILURE_PHASES = {"test", "build"}

_TEST = re.compile(r"\b(vitest|jest|pytest|go test|cargo test|npm (run )?(test|check)|pnpm (run )?test|tsc\b|mypy|ruff|eslint)")
_BUILD = re.compile(r"\b(npm run build|pnpm build|cargo build|go build|make\b|docker build)")
_COMMIT = re.compile(r"\bgit (commit|push|add|merge|rebase|tag)\b")
_EXPLORE = re.compile(r"^\s*(cd\s+\S+\s*&&\s*)?(grep|rg|cat|sed -n|ls|find|head|tail|wc|git (log|diff|status|show|branch)|tree)\b")


def phase_of(tool: str, tool_input: dict[str, Any] | None = None) -> str | None:
    """Map one tool call to a phase. Arguments are inspected, never stored."""
    name = tool or ""
    if name in {"Read", "Grep", "Glob", "LS", "NotebookRead"}:
        return "explore"
    if name in {"Edit", "Write", "MultiEdit", "NotebookEdit"}:
        return "edit"
    if name == "Bash":
        cmd = str((tool_input or {}).get("command", ""))
        if _TEST.search(cmd):
            return "test"
        if _BUILD.search(cmd):
            return "build"
        if _COMMIT.search(cmd):
            return "commit"
        if _EXPLORE.search(cmd):
            return "explore"
        return "shell"
    if name in {"Agent", "Task"}:
        return "subagent"
    if name == "Skill":
        return "skill"
    if name in {"WebFetch", "WebSearch"} or "chrome" in name.lower() or "browser" in name.lower():
        return "web"
    if name.startswith("mcp__agentctl") or name.startswith("worker:") or name.startswith("agentctl_"):
        return "delegate"
    if name.startswith("mcp__"):
        return "shell"
    return None


@dataclass(slots=True)
class Request:
    session: str
    harness: str
    day: str
    phases: list[str] = field(default_factory=list)
    anchor: str | None = None
    model: str | None = None
    steps: int = 0
    error_steps: int = 0
    # errors on steps where failing is not the point (edit, explore, shell, delegate, web...);
    # a failing test or build is feedback, not friction
    friction_errors: int = 0
    error_phases: dict[str, int] = field(default_factory=dict)
    ended_in_error: bool = False
    output_tokens: int = 0
    duration_ms: int = 0

    @property
    def shape(self) -> tuple[str, ...]:
        compact = [p for i, p in enumerate(self.phases) if i == 0 or p != self.phases[i - 1]]
        return tuple(compact[:MAX_SHAPE])


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_COMMAND = re.compile(r"<command-name>/?([\w:.-]{1,60})</command-name>")
_BORING_COMMANDS = {"clear", "model", "mcp", "effort", "reload-plugins", "reload-skills", "remote-env", "resume", "compact", "config", "help", "cost", "exit"}


def read_claude_code(root: str | Path, since: datetime | None = None) -> list[Request]:
    """Requests from Claude Code transcripts (~/.claude/projects/**/*.jsonl).

    The transcript format is internal to Claude Code and may change; this reader
    only relies on `type`, `timestamp`, `message.model`, `message.usage`,
    `message.content[].type/name/is_error` and the `<command-name>` marker.
    """
    requests: list[Request] = []
    for path in sorted(Path(root).expanduser().glob("**/*.jsonl")):
        if "subagents" in path.parts:
            continue
        requests.extend(_read_claude_file(path, since))
    return requests


def _read_claude_file(path: Path, since: datetime | None) -> list[Request]:
    out: list[Request] = []
    cur: Request | None = None
    started: datetime | None = None
    last: datetime | None = None
    seen_usage: dict[str, int] = {}
    phase_of_call: dict[str, str] = {}
    last_tool_error = False

    def flush() -> None:
        nonlocal cur
        if cur is not None and (cur.steps or cur.output_tokens):
            if started and last:
                cur.duration_ms = max(0, int((last - started).total_seconds() * 1000))
            cur.ended_in_error = last_tool_error and cur.steps > 0
            out.append(cur)
        cur = None

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        ts = _ts(rec.get("timestamp"))
        if since and ts and ts < since:
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        kind = rec.get("type")
        if kind == "user" and isinstance(msg.get("content"), str) and not rec.get("isMeta"):
            m = _COMMAND.search(msg["content"])
            command = m.group(1) if m else None
            if command in _BORING_COMMANDS:
                continue  # housekeeping commands are not workflows
            flush()
            cur = Request(session=path.stem, harness="claude-code", day=(ts or datetime.min).date().isoformat(),
                          anchor=f"/{command}" if command else None)
            started = ts
            last = ts
            last_tool_error = False
            continue
        if cur is None:
            continue
        if ts:
            last = ts
        if kind == "assistant":
            if msg.get("model") and not str(msg["model"]).startswith("<"):
                cur.model = msg["model"]
            mid = msg.get("id")
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            out_tokens = usage.get("output_tokens")
            if isinstance(out_tokens, int) and mid:
                # Claude Code writes one line per content block with the message's usage repeated.
                cur.output_tokens += out_tokens - seen_usage.get(mid, 0) if out_tokens > seen_usage.get(mid, 0) else 0
                seen_usage[mid] = max(out_tokens, seen_usage.get(mid, 0))
            for block in msg.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = str(block.get("name", ""))
                if name == "Skill" and cur.anchor is None:
                    skill = (block.get("input") or {}).get("skill")
                    if isinstance(skill, str) and re.fullmatch(r"[\w:.-]{1,60}", skill):
                        cur.anchor = f"skill:{skill}"
                phase = phase_of(name, block.get("input") if isinstance(block.get("input"), dict) else None)
                cur.steps += 1
                if phase:
                    cur.phases.append(phase)
                    if isinstance(block.get("id"), str):
                        phase_of_call[block["id"]] = phase
        elif kind == "user":
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        last_tool_error = bool(block.get("is_error"))
                        if last_tool_error:
                            cur.error_steps += 1
                            ph = phase_of_call.get(str(block.get("tool_use_id")), "other")
                            cur.error_phases[ph] = cur.error_phases.get(ph, 0) + 1
                            if ph not in EXPECTED_FAILURE_PHASES:
                                cur.friction_errors += 1
    flush()
    return out


def read_generic(paths: Iterable[str | Path]) -> list[Request]:
    """Requests from SessionGraph-loadable sessions (Pi, agentctl exports, generic JSONL): one request per session."""
    from .parsers import load_session  # local import: parsers pulls optional pieces

    out: list[Request] = []
    for p in paths:
        try:
            session = load_session(Path(p))
        except Exception:  # noqa: BLE001 - one unreadable file must not stop mining
            continue
        req = Request(session=session.id, harness=session.format, day="")
        root = session.events[0] if session.events else None
        is_agentctl_job = any((ev.name or "").startswith(("worker:", "orchestrator:")) for ev in session.events)
        if is_agentctl_job and root is not None and ":" in (root.name or ""):
            # agentctl job graphs: the root is "<caller>:<kind>"; a job is its own workflow, not the caller's delegation
            req.harness = "agentctl"
            req.anchor = f"agentctl:{(root.name or '').split(':', 1)[1]}"
        first = last = None
        for ev in session.events:
            ts = _ts(getattr(ev, "timestamp", None))
            if ts:
                first = first or ts
                last = ts
            if ev.kind in {"tool_call", "loop_generate"} or (ev.kind == "tool_call"):
                req.steps += 1
                ph = phase_of(ev.name or "", None)
                if ph:
                    req.phases.append(ph)
            if ev.kind in {"tool_result"} and ev.is_error:
                req.error_steps += 1
        if first:
            req.day = first.date().isoformat()
            req.duration_ms = int(((last or first) - first).total_seconds() * 1000)
        if req.steps:
            out.append(req)
    return out


def family_of(req: Request) -> str:
    """A deterministic, human-readable workflow family."""
    if req.anchor:
        return req.anchor
    s = set(req.phases)
    if not s:
        return "answer-only"
    if s <= {"explore", "web"}:
        return "research" if "web" in s else "lookup"
    if "delegate" in s and not ({"edit", "test"} & s):
        return "delegate"
    if "commit" in s:
        return "ship"
    if "edit" in s and "test" in s:
        return "edit-test"
    if "edit" in s:
        return "edit"
    if "test" in s or "build" in s:
        return "verify"
    return "shell"


def _entropy(counts: Iterable[int]) -> float:
    total = sum(counts)
    if not total:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counts if c)


def _dfg(shapes: Iterable[tuple[str, ...]]) -> dict[str, int]:
    edges: Counter[str] = Counter()
    for shape in shapes:
        seq = ("START", *shape, "END")
        for a, b in zip(seq, seq[1:]):
            edges[f"{a}>{b}"] += 1
    return dict(edges.most_common())


def typical_path(dfg: dict[str, int], limit: int = MAX_SHAPE) -> list[str]:
    """Greedy walk from START along the most frequent transitions, never revisiting a phase.

    More representative than the most common variant when no variant dominates.
    """
    out: list[str] = []
    here = "START"
    while len(out) < limit:
        options = sorted(((c, e.split(">", 1)[1]) for e, c in dfg.items() if e.split(">", 1)[0] == here), reverse=True)
        nxt = next((b for _, b in options if b not in out and b != "START"), None)
        if nxt is None or nxt == "END":
            break
        out.append(nxt)
        here = nxt
    return out


def mine(requests: list[Request]) -> dict[str, Any]:
    """Families with their DFG, variants and cost/failure profile."""
    groups: dict[str, list[Request]] = defaultdict(list)
    for r in requests:
        groups[family_of(r)].append(r)
    total = len(requests) or 1
    families = []
    for name, reqs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        variants = Counter(r.shape for r in reqs)
        steps = [r.steps for r in reqs]
        tokens = [r.output_tokens for r in reqs if r.output_tokens]
        errs = sum(1 for r in reqs if r.error_steps)
        families.append({
            "family": name,
            "requests": len(reqs),
            "share": round(len(reqs) / total, 3),
            "sessions": len({r.session for r in reqs}),
            "days": len({r.day for r in reqs if r.day}),
            "harnesses": dict(Counter(r.harness for r in reqs)),
            "models": dict(Counter(r.model or "unknown" for r in reqs).most_common(4)),
            "median_steps": median(steps) if steps else 0,
            "median_output_tokens": int(median(tokens)) if tokens else None,
            "total_output_tokens": sum(tokens),
            "median_seconds": round(median([r.duration_ms for r in reqs]) / 1000, 1) if reqs else 0,
            # share of runs that hit any tool error (normal in development: a failing test, an empty grep)
            "error_rate": round(errs / len(reqs), 3),
            "ended_in_error": sum(1 for r in reqs if r.ended_in_error),
            # share of runs whose last tool call failed: errors the run did not recover from
            "unrecovered_rate": round(sum(1 for r in reqs if r.ended_in_error) / len(reqs), 3),
            # share of runs with friction: a tool other than test/build failed
            "friction_rate": round(sum(1 for r in reqs if r.friction_errors) / len(reqs), 3),
            "error_phases": dict(sum((Counter(r.error_phases) for r in reqs), Counter()).most_common()),
            "variants": [{"shape": list(s), "count": c} for s, c in variants.most_common(6)],
            "variant_count": len(variants),
            "dominant_share": round(variants.most_common(1)[0][1] / len(reqs), 3) if reqs else 0,
            "variant_entropy": round(_entropy(variants.values()), 3),
            "dfg": _dfg(r.shape for r in reqs),
        })
        families[-1]["typical_path"] = typical_path(families[-1]["dfg"])
    return {
        "schema": SCHEMA,
        "requests": len(requests),
        "sessions": len({r.session for r in requests}),
        "days": sorted({r.day for r in requests if r.day}),
        "families": families,
    }


def request_rows(requests: list[Request]) -> list[dict[str, Any]]:
    """Per-request rows (content-free) for export or debugging."""
    return [{**asdict(r), "shape": list(r.shape), "family": family_of(r)} for r in requests]
