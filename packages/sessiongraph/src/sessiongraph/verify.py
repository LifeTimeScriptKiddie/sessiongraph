"""Verify detectors against human labels before their findings are trusted.

A detector is code that answers yes or no for one turn. Its answer is only
passed on as a finding once human labels show it is right often enough:
precision on the turns it flagged, and recall estimated from a random sample
of turns it did not flag. Labels written by an agent never count.

This module verifies user-correction detectors over Claude Code transcripts:

- keyword_any_author: today's analyze.py rule (correction words in any user turn)
- keyword_human:      the same rule, restricted to turns a human typed
- behavior:           observable behavior only: the human stopped the previous
                      run (interrupt or rejected tool call), or the agent reverted
                      work right after the turn

Label sheets are content-free: they store transcript paths and turn ids. The
`label` command re-reads each turn's text from the transcript at labeling time.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .analyze import CORRECTION_TERMS
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


def label_sheet(turns: list[Turn], sample: int = 40, seed: int = 7) -> list[dict[str, Any]]:
    """Rows to label: every flagged turn, plus a seeded sample of unflagged human turns for recall."""
    flagged, unflagged = [], []
    for turn in turns:
        flags = {name: detect(turn) for name, detect in DETECTORS.items()}
        row = {"turn_id": turn.id, "path": turn.path, "author": turn.author,
               "author_reason": turn.author_reason, "flags": flags,
               "signals": {"stopped_before": turn.stopped_before, "reverted_after": turn.reverted_after},
               "label": None, "labeled_by": None}
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
    human = [r for r in body if r.get("labeled_by") == "human" and isinstance(r.get("label"), bool)]
    ignored = sum(r.get("label") is not None and r.get("labeled_by") != "human" for r in body)
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
    return {"schema": REPORT_SCHEMA, "thresholds": t, "human_labels": len(human),
            "ignored_non_human_labels": ignored,
            "unlabeled": sum(not isinstance(r.get("label"), bool) for r in body),
            "sample": {"labeled": len(sample), "true_rate": _rate(sum(r["label"] for r in sample), len(sample)),
                       "unflagged_human": header["unflagged_human"]},
            "authors": header["authors"], "detectors": results}
