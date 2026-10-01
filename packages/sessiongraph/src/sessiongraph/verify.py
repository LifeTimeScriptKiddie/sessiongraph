"""Verify detectors against human labels before their findings are trusted.

A detector is code that answers yes or no for one turn. Its answer is only
passed on as a finding once human labels show it is right often enough:
precision on the turns it flagged, and recall estimated from a random sample
of turns it did not flag. Labels written by an agent never count; turns a
human did not type are settled as "no" by code (`labeled_by: code`).

This module verifies user-correction detectors over Claude Code transcripts:

- keyword_any_author: today's analyze.py rule (correction words in any user turn)
- keyword_human:      the same rule, restricted to turns a human typed
- behavior:           observable behavior only: the human stopped the previous
                      run (interrupt or rejected tool call), or the agent reverted
                      work right after the turn

It also verifies the loop detectors (repeated_action, alternating_loop) per
request: a typed turn and every tool call the agent made for it.

Label sheets are content-free: they store transcript paths and turn ids. The
`label` command re-reads each turn's text, or a request's tool calls, from the
transcript at labeling time.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .analyze import CORRECTION_TERMS, _alternating, _repeated
from .model import Event
from .privacy import fingerprint, sanitize
from .workflows import _ts

SCHEMA = "sessiongraph.labels.v1"
REPORT_SCHEMA = "sessiongraph.detector-verification.v1"
THRESHOLDS: dict[str, float] = {"min_labeled_flagged": 10, "precision": 0.8, "recall": 0.5}

_INTERRUPT = re.compile(r"\[Request interrupted by user")
_REVERT = re.compile(r"\bgit (checkout --|restore\b|revert\b|reset --hard\b|stash\b)")
_COMPACTION = "This session is being continued from a previous conversation"
REVERT_WINDOW = 5  # tool calls after the turn that may count as reverting work


@dataclass(slots=True)
class Turn:
    id: str
    path: str
    author: str  # human | agent | system | unknown
    author_reason: str
    text: str = ""  # held in memory for detectors; never written to a sheet or report
    stopped_before: bool = False
    reverted_after: bool = False


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
    if text.startswith(_COMPACTION):
        return "system", "compaction summary"
    return "unknown", "no origin marker"


def _turn_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and all(
            isinstance(b, dict) and b.get("type") == "text" for b in content):
        return "\n".join(str(b.get("text", "")) for b in content)
    return None


def read_turns(path: Path, since: datetime | None = None) -> list[Turn]:
    """User turns of one Claude Code transcript, with the behavior around each."""
    turns: list[Turn] = []
    stopped = False
    calls_since_turn = REVERT_WINDOW
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return turns
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
        if rec.get("type") == "assistant":
            for block in msg.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                calls_since_turn += 1
                command = str((block.get("input") or {}).get("command", "")) if block.get("name") == "Bash" else ""
                if calls_since_turn <= REVERT_WINDOW and _REVERT.search(command) and turns:
                    turns[-1].reverted_after = True
            continue
        if rec.get("type") != "user":
            continue
        if rec.get("toolDenialKind") == "user-rejected":
            stopped = True
            continue
        text = _turn_text(msg.get("content"))
        if text is None:
            continue
        if _INTERRUPT.match(text.strip()):
            stopped = True
            continue
        text = text.strip()
        if not text or text.startswith("<"):
            continue  # command wrappers, local command output, notifications
        author, reason = author_of(rec, text)
        turn_id = str(rec.get("uuid") or f"line-{len(turns)}")
        turns.append(Turn(turn_id, str(path), author, reason, text, stopped_before=stopped and author == "human"))
        if author in {"human", "unknown"}:  # the next typed turn consumes the stop, whoever wrote it
            stopped = False
            calls_since_turn = 0
    return turns


def read_claude_turns(root: str | Path, since: datetime | None = None) -> list[Turn]:
    out: list[Turn] = []
    for path in sorted(Path(root).expanduser().glob("**/*.jsonl")):
        if "subagents" not in path.parts:
            out.extend(read_turns(path, since))
    return out


def _keyword(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in CORRECTION_TERMS)


DETECTORS: dict[str, Callable[[Turn], bool]] = {
    "keyword_any_author": lambda t: _keyword(t.text),
    "keyword_human": lambda t: t.author == "human" and _keyword(t.text),
    "behavior": lambda t: t.author == "human" and (t.stopped_before or t.reverted_after),
}


@dataclass(slots=True)
class Request:
    """A typed turn and the agent's tool calls for it, as analyze-compatible events."""
    id: str
    path: str
    author: str
    author_reason: str
    events: list[Event]
    calls: list[dict[str, Any]]  # for display at labeling time only; never written to a sheet


def _call_summary(name: str, tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "pattern", "url", "query", "skill", "description", "prompt"):
            if isinstance(tool_input.get(key), str):
                return " ".join(tool_input[key].split())[:110]
    return ""


def read_requests(path: Path, since: datetime | None = None) -> list[Request]:
    """Requests of one Claude Code transcript. System turns (notifications, summaries) start none."""
    requests: list[Request] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return requests
    by_call: dict[str, dict[str, Any]] = {}
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
        content = msg.get("content")
        if rec.get("type") == "user":
            text = _turn_text(content)
            if text is not None:
                text = text.strip()
                if text and not text.startswith("<") and not _INTERRUPT.match(text):
                    author, reason = author_of(rec, text)
                    if author != "system":
                        uid = str(rec.get("uuid") or f"line-{len(requests)}")
                        requests.append(Request(uid, str(path), author, reason,
                                                [Event(uid, None, "message", role="user")], []))
                continue
            if requests and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        call_id = str(block.get("tool_use_id"))
                        error = bool(block.get("is_error"))
                        requests[-1].events.append(Event(f"r-{call_id}", call_id, "tool_result", is_error=error))
                        if call_id in by_call:
                            body = block.get("content")
                            body = body if isinstance(body, str) else json.dumps(body, default=str)
                            by_call[call_id].update(error=error, result=" ".join(body.split())[:110])
        elif rec.get("type") == "assistant" and requests:
            for block in content or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call_id, name = str(block.get("id")), str(block.get("name", "unknown"))
                safe_args, _ = sanitize(block.get("input", {}))
                current = requests[-1]
                current.events.append(Event(call_id, current.events[-1].id, "tool_call", role="assistant", name=name,
                                            signature=fingerprint("tool_call", name, safe_args)))
                by_call[call_id] = {"id": call_id, "name": name, "input": _call_summary(name, block.get("input"))}
                current.calls.append(by_call[call_id])
    return requests


def read_claude_requests(root: str | Path, since: datetime | None = None) -> list[Request]:
    out: list[Request] = []
    for path in sorted(Path(root).expanduser().glob("**/*.jsonl")):
        if "subagents" not in path.parts:
            out.extend(read_requests(path, since))
    return out


def _same_tool_failing(request: Request, minimum: int = 3) -> list[str]:
    """Candidate: one tool fails >= 3 times in a request, whatever its arguments.

    The analyze detectors need identical calls; agents usually change arguments
    when they retry, so this asks the same question without that requirement.
    """
    failed = {e.parent_id for e in request.events if e.kind == "tool_result" and e.is_error}
    by_tool: dict[str, list[str]] = {}
    for event in request.events:
        if event.kind == "tool_call" and event.id in failed:
            by_tool.setdefault(event.name or "unknown", []).append(event.id)
    return [call for calls in by_tool.values() if len(calls) >= minimum for call in calls]


LOOP_DETECTORS: dict[str, Callable[[Request], list[str]]] = {
    # each returns the evidence event ids it flagged (empty = no)
    "repeated_action": lambda r: [e for f in _repeated(r.events) for e in f.evidence],
    "alternating_loop": lambda r: [e for f in _alternating(r.events) for e in f.evidence],
    "same_tool_failing": _same_tool_failing,
}
MIN_LOOP_SAMPLE_CALLS = 4  # a request with fewer calls cannot hold an A-B-A-B loop


def loop_sheet(requests: list[Request], sample: int = 40, seed: int = 7) -> list[dict[str, Any]]:
    """Rows to label: every flagged request, plus a seeded sample of unflagged ones with >= 4 tool calls."""
    flagged, unflagged = [], []
    for request in requests:
        hits = {name: detect(request) for name, detect in LOOP_DETECTORS.items()}
        row = {"turn_id": request.id, "path": request.path, "author": request.author,
               "author_reason": request.author_reason, "flags": {name: bool(ids) for name, ids in hits.items()},
               "signals": {"tool_calls": len(request.calls),
                           "errors": sum(e.kind == "tool_result" and e.is_error for e in request.events)},
               "label": None, "labeled_by": None}
        if any(row["flags"].values()):
            flagged.append({**row, "stratum": "flagged"})
        elif len(request.calls) >= MIN_LOOP_SAMPLE_CALLS:
            unflagged.append({**row, "stratum": "sample"})
    picked = random.Random(seed).sample(unflagged, min(sample, len(unflagged)))
    header = {"schema": SCHEMA, "kind": "header", "unit": "request",
              "question": "Was the agent stuck in a loop here, repeating similar steps without making progress?",
              "turns": len(requests), "authors": {a: sum(r.author == a for r in requests)
                                                   for a in ("human", "agent", "unknown")},
              "unflagged_human": len(unflagged), "sample_size": len(picked), "seed": seed,
              "detectors": sorted(LOOP_DETECTORS)}
    return [header, *flagged, *picked]


_CD_PREFIX = re.compile(r"^cd\s+\S+\s*&&\s*")
_NOISE = re.compile(r"</?tool_use_error>|^Exit code \d+\s*")


def _short(text: str, width: int) -> str:
    text = " ".join(text.replace(str(Path.home()), "~").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _what(call: dict[str, Any]) -> str:
    return _short(_CD_PREFIX.sub("", call["input"]), 48)


def _why(call: dict[str, Any]) -> str:
    return _short(_NOISE.sub("", call.get("result", "")).strip() or "(no message)", 60)


def request_text(row: dict[str, Any]) -> str:
    """A short, blind summary of one request: the ask, failures in full, successful runs collapsed.

    It does not say which detector flagged the request, so the labeler is not nudged.
    """
    for request in read_requests(Path(row["path"])):
        if request.id != row["turn_id"]:
            continue
        calls = request.calls
        failed = [c for c in calls if c.get("error")]
        lines = [f"You asked: {_short(_request_prompt(row) or '(prompt not shown)', 110)}", "",
                 f"The agent made {len(calls)} tool call(s); {len(failed)} failed."]
        if failed:
            by_tool: dict[str, int] = {}
            for call in failed:
                by_tool[call["name"]] = by_tool.get(call["name"], 0) + 1
            lines.append("Failures by tool: " + ", ".join(f"{n} ×{k}" for n, k in by_tool.items()))
        lines.append("")
        run: list[tuple[int, dict[str, Any]]] = []

        def flush() -> None:
            if not run:
                return
            first, last = run[0][0], run[-1][0]
            tools: dict[str, int] = {}
            for _, call in run:
                tools[call["name"]] = tools.get(call["name"], 0) + 1
            span = f"{first}" if first == last else f"{first}-{last}"
            lines.append(f"  {span:>7}  ok    " + ", ".join(f"{n} ×{k}" if k > 1 else n for n, k in tools.items()))
            run.clear()

        for index, call in enumerate(calls, 1):
            if not call.get("error"):
                run.append((index, call))
                continue
            flush()
            lines.append(f"  {index:>7}  FAIL  {call['name']}: {_what(call)}")
            lines.append(f"  {'':>7}        why: {_why(call)}")
        flush()
        return "\n".join(lines)
    return "(request not found: transcript changed or moved)"


def _request_prompt(row: dict[str, Any]) -> str:
    for turn in read_turns(Path(row["path"])):
        if turn.id == row["turn_id"]:
            return turn.text
    return ""


def label_sheet(turns: list[Turn], sample: int = 40, seed: int = 7) -> list[dict[str, Any]]:
    """Rows to label: every flagged turn, plus a seeded sample of unflagged human turns for recall."""
    flagged, unflagged = [], []
    for turn in turns:
        flags = {name: detect(turn) for name, detect in DETECTORS.items()}
        row = {"turn_id": turn.id, "path": turn.path, "author": turn.author,
               "author_reason": turn.author_reason, "flags": flags,
               "signals": {"stopped_before": turn.stopped_before, "reverted_after": turn.reverted_after},
               "label": None, "labeled_by": None}
        if turn.author != "human":
            # a turn nobody typed cannot be a human correction: settled from recorded fields, not judged
            row.update(label=False, labeled_by="code")
        if any(flags.values()):
            flagged.append({**row, "stratum": "flagged"})
        elif turn.author == "human":
            unflagged.append({**row, "stratum": "sample"})
    picked = random.Random(seed).sample(unflagged, min(sample, len(unflagged)))
    authors = {a: sum(t.author == a for t in turns) for a in ("human", "agent", "system", "unknown")}
    header = {"schema": SCHEMA, "kind": "header",
              "question": "Is this a human correcting or redirecting the agent's previous work?",
              "turns": len(turns), "authors": authors, "unflagged_human": len(unflagged),
              "sample_size": len(picked), "seed": seed, "detectors": sorted(DETECTORS)}
    return [header, *flagged, *picked]


def read_sheet(path: str | Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or rows[0].get("schema") != SCHEMA or rows[0].get("kind") != "header":
        raise ValueError(f"{path}: expected a {SCHEMA} sheet with a header row")
    return rows


def write_sheet(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    Path(path).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def turn_text(row: dict[str, Any]) -> str:
    """Re-read one turn's text from its transcript, for a human labeler to judge."""
    for turn in read_turns(Path(row["path"])):
        if turn.id == row["turn_id"]:
            return turn.text
    return "(turn not found: transcript changed or moved)"


def _rate(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def verify(rows: list[dict[str, Any]], t: dict[str, float] = THRESHOLDS) -> dict[str, Any]:
    """Precision and estimated recall per detector, from human labels only."""
    header, body = rows[0], rows[1:]
    human = [r for r in body if isinstance(r.get("label"), bool) and (
        r.get("labeled_by") == "human" or (r.get("labeled_by") == "code" and r.get("author") != "human"))]
    ignored = sum(r.get("label") is not None and r not in human for r in body)
    sample = [r for r in human if r["stratum"] == "sample"]
    sample_true_rate = sum(r["label"] for r in sample) / len(sample) if sample else None
    missed_unflagged = (sample_true_rate or 0) * header["unflagged_human"]
    results = {}
    for name in header["detectors"]:
        hits = [r for r in human if r["stratum"] == "flagged" and r["flags"].get(name)]
        tp = sum(r["label"] for r in hits)
        # true corrections flagged by another detector but not this one: counted exactly
        missed_flagged = sum(r["label"] for r in human if r["stratum"] == "flagged" and not r["flags"].get(name))
        precision = _rate(tp, len(hits))
        recall = _rate(tp, tp + missed_flagged + missed_unflagged) if sample_true_rate is not None else None
        if len(hits) < t["min_labeled_flagged"] or recall is None:
            verdict = "insufficient_labels"
        elif precision >= t["precision"] and recall >= t["recall"]:
            verdict = "verified"
        else:
            verdict = "unverified"
        results[name] = {"labeled_flagged": len(hits), "true_positives": tp, "false_positives": len(hits) - tp,
                         "precision": precision, "missed_in_flagged": missed_flagged,
                         "missed_estimated_unflagged": round(missed_unflagged, 1),
                         "recall_estimated": recall, "verdict": verdict}
    return {"schema": REPORT_SCHEMA, "thresholds": t,
            "human_labels": sum(r["labeled_by"] == "human" for r in human),
            "code_labels": sum(r["labeled_by"] == "code" for r in human),
            "ignored_non_human_labels": ignored,
            "unlabeled": sum(not isinstance(r.get("label"), bool) for r in body),
            "sample": {"labeled": len(sample), "true_rate": _rate(sum(r["label"] for r in sample), len(sample)),
                       "unflagged_human": header["unflagged_human"]},
            "authors": header["authors"], "detectors": results}
