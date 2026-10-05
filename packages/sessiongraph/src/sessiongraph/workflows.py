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

import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .repos import UNKNOWN, display, git_root, repo_of, slugs

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
    repo: str = "unknown"  # git root of the session's cwd (repos.repo_of); worktrees count as their main repo
    branch: str | None = None
    # how repo was found: "cwd" (a git repo), "touched" (cwd outside git; most tool calls touched this repo),
    # "folder" (cwd outside git, no single touched repo) or "unknown" (cwd gone)
    repo_source: str = "unknown"

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
    """Requests of one transcript, from the shared Claude Code reader (claude_code.py)."""
    from .claude_code import is_boring, read_transcript, segment  # local import: claude_code imports this module

    session = read_transcript(path, since, subagents=False)
    out: list[Request] = []

    def starts(turn) -> bool:
        return bool(turn.metadata.get("string_content")) and not turn.metadata.get("meta") and not is_boring(turn)

    for part in segment(session, starts):
        command = part.turn.metadata.get("command")
        started = last = _ts(part.turn.timestamp)
        req = Request(session=path.stem, harness="claude-code", day=(started or datetime.min).date().isoformat(),
                      anchor=f"/{command}" if command else None, repo=repo_of(part.turn.metadata.get("cwd")),
                      branch=part.turn.metadata.get("git_branch"))
        phase_of_call: dict[str, str] = {}
        touched: Counter[str] = Counter()
        last_tool_error = False
        for event in part.events:
            if event.kind == "message" and event.role == "user" and is_boring(event):
                continue  # housekeeping commands are not part of the request's timeline
            ts = _ts(event.timestamp)
            if ts:
                last = ts
            if event.kind == "message" and event.role == "assistant":
                if event.metadata.get("model"):
                    req.model = event.metadata["model"]
                req.output_tokens += event.metadata.get("output_tokens") or 0
            elif event.kind == "tool_call":
                skill = event.metadata.get("skill")
                if skill and req.anchor is None:
                    req.anchor = f"skill:{skill}"
                req.steps += 1
                phase = event.metadata.get("phase")
                if phase:
                    req.phases.append(phase)
                    phase_of_call[event.id] = phase
                if event.metadata.get("touched_repo"):
                    touched[event.metadata["touched_repo"]] += 1
            elif event.kind == "tool_result":
                last_tool_error = event.is_error
                if last_tool_error:
                    req.error_steps += 1
                    ph = phase_of_call.get(str(event.parent_id), "other")
                    req.error_phases[ph] = req.error_phases.get(ph, 0) + 1
                    if ph not in EXPECTED_FAILURE_PHASES:
                        req.friction_errors += 1
        _settle_repo(req, part.turn.metadata.get("cwd"), touched)
        if req.steps or req.output_tokens:
            if started and last:
                req.duration_ms = max(0, int((last - started).total_seconds() * 1000))
            req.ended_in_error = last_tool_error and req.steps > 0
            out.append(req)
    return out


def _settle_repo(req: Request, cwd: str | None, touched: Counter[str]) -> None:
    """Keep the cwd's repo when it is one; otherwise use the repo most tool calls touched, if it is a clear majority."""
    if req.repo == UNKNOWN:
        req.repo_source = "unknown"
    elif git_root(cwd):
        req.repo_source = "cwd"
    else:
        req.repo_source = "folder"
    if req.repo_source != "cwd" and touched:
        repo, hits = touched.most_common(1)[0]
        if hits * 2 > sum(touched.values()):
            req.repo, req.repo_source = repo, "touched"


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
        return ship_kind(req.phases)
    if "edit" in s and "test" in s:
        return "edit-test"
    if "edit" in s:
        return "edit"
    if "test" in s or "build" in s:
        return "verify"
    return "shell"


def ship_kind(phases: list[str]) -> str:
    """Split ship by what ran before the first commit (explore, web, delegate... do not count).

    - ship:edit-test       edited, then tested or built
    - ship:edit-untested   edited, nothing tested or built (a commit no check covered)
    - ship:shell           no edit; shell commands (scripts, config, generated files)
    - ship:commit-only     nothing changed here first: committing earlier work (a test run alone is allowed)
    """
    before = set(phases[:phases.index("commit")])
    if "edit" in before:
        return "ship:edit-test" if before & {"test", "build"} else "ship:edit-untested"
    if "shell" in before:
        return "ship:shell"
    return "ship:commit-only"


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


def mine(requests: list[Request], by_repo: bool = False) -> dict[str, Any]:
    """Families with their DFG, variants and cost/failure profile.

    With by_repo, a family is split per repository and named `<repo>/<family>`, so one
    repo's habits are judged on their own instead of being blended with every other repo.
    """
    short = slugs({r.repo for r in requests})
    groups: dict[str, list[Request]] = defaultdict(list)
    for r in requests:
        groups[f"{short[r.repo]}/{family_of(r)}" if by_repo else family_of(r)].append(r)
    total = len(requests) or 1
    per_repo = Counter(r.repo for r in requests)
    families = []
    for name, reqs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        variants = Counter(r.shape for r in reqs)
        steps = [r.steps for r in reqs]
        tokens = [r.output_tokens for r in reqs if r.output_tokens]
        errs = sum(1 for r in reqs if r.error_steps)
        families.append({
            "family": name,
            "base_family": family_of(reqs[0]),
            "repo": display(reqs[0].repo) if by_repo else None,
            # where this family ran: repo -> requests (content-free: repo paths only)
            "repos": {display(k): v for k, v in Counter(r.repo for r in reqs).most_common()},
            "branches": len({(r.repo, r.branch) for r in reqs if r.branch}),
            "requests": len(reqs),
            # share of all requests, or of its repo's requests when split by repo
            "share": round(len(reqs) / (per_repo[reqs[0].repo] if by_repo else total), 3),
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
    from .claude_code import READER  # local import: claude_code imports this module

    return {
        "schema": SCHEMA,
        # which reader produced the requests, so a count change can be traced to a reader change
        "readers": {"claude-code": READER} if any(r.harness == "claude-code" for r in requests) else {},
        "requests": len(requests),
        "by_repo": by_repo,
        "repos": {display(k): v for k, v in Counter(r.repo for r in requests).most_common()},
        "repo_sources": dict(Counter(r.repo_source for r in requests).most_common()),
        "sessions": len({r.session for r in requests}),
        "days": sorted({r.day for r in requests if r.day}),
        "families": families,
    }


def request_rows(requests: list[Request]) -> list[dict[str, Any]]:
    """Per-request rows (content-free) for export or debugging."""
    return [{**asdict(r), "shape": list(r.shape), "family": family_of(r)} for r in requests]
