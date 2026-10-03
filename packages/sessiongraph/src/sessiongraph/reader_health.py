"""Detect Claude Code transcript format drift before trusting what the reader returns.

Claude Code calls its transcript format internal, so a field can be renamed
without notice. The reader would then return empty or wrong events, and every
check built on them would quietly report "nothing found". This module answers
one yes/no question per run: did the reader see the transcripts the way they
are written?

It uses two independent views:

- raw: a plain JSON walk of every record that knows nothing about the reader
- reader: what claude_code.read_transcript produced from the same file

Drift is any absolute limit broken, or the two views disagreeing on how many
tool calls, tool results and user turns there are. With --baseline, coverage
rates must also not fall far below the last healthy run. Everything here is
counts, never transcript content.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .claude_code import read_transcript, transcripts, turn_text

SCHEMA = "sessiongraph.reader-health.v1"
KNOWN_BLOCKS = {"text", "tool_use", "tool_result", "thinking", "redacted_thinking", "image", "document", "fallback"}
CONVERSATION = {"user", "assistant"}
# Absolute limits: above (or for conversation_share, below) these the reader can't be trusted.
LIMITS: dict[str, float] = {
    "parse_error_rate": 0.01,
    "missing_message_rate": 0.01,
    "unknown_block_rate": 0.01,
    "unpaired_result_rate": 0.05,
    "conversation_share_min": 0.05,  # share checked from MIN_RECORDS records; zero conversation is always drift
}
MIN_RECORDS = 20
BASELINE_MAX_DROP = 0.2  # coverage rates may not fall more than this below the baseline


def raw_scan(path: Path) -> dict[str, Any]:
    """Counts from a plain JSON walk, independent of the reader."""
    stats: Counter[str] = Counter()
    record_types: Counter[str] = Counter()
    block_types: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    call_ids: set[str] = set()
    result_ids: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {"unreadable": 1}
    for line in lines:
        if not line.strip():
            continue
        stats["records"] += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            stats["parse_errors"] += 1
            continue
        if not isinstance(rec, dict):
            stats["parse_errors"] += 1
            continue
        kind = rec.get("type")
        record_types[str(kind)] += 1
        if isinstance(rec.get("version"), str):
            versions[rec["version"]] += 1
        if kind not in CONVERSATION:
            continue
        stats["conversation"] += 1
        msg = rec.get("message")
        if not isinstance(msg, dict):
            stats["missing_message"] += 1
            continue
        content = msg.get("content")
        if kind == "assistant":
            stats["assistant"] += 1
            usage = msg.get("usage")
            stats["assistant_with_usage"] += isinstance(usage, dict) and isinstance(usage.get("output_tokens"), int)
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = str(block.get("type"))
                block_types[btype] += 1
                stats["blocks"] += 1
                stats["unknown_blocks"] += btype not in KNOWN_BLOCKS
                if kind == "assistant" and btype == "tool_use":
                    stats["tool_use"] += 1
                    call_ids.add(str(block.get("id")))
                if kind == "user" and btype == "tool_result":
                    stats["tool_result"] += 1
                    result_ids.append(str(block.get("tool_use_id")))
        if kind == "user" and turn_text(content) is not None:
            stats["user_text"] += 1
            if not rec.get("isMeta") and isinstance(content, str) and not content.lstrip().startswith("<"):
                stats["typed"] += 1
                # only fields that say who typed the turn; entrypoint is on every record and proves nothing
                stats["typed_with_origin"] += bool(rec.get("origin") or rec.get("promptSource") or rec.get("turnOrigin"))
    stats["unpaired_results"] = sum(rid not in call_ids for rid in result_ids)
    return {**stats, "record_types": dict(record_types), "block_types": dict(block_types), "versions": dict(versions)}


def reader_counts(path: Path) -> dict[str, int]:
    events = read_transcript(path, subagents=False).events
    return {
        "tool_use": sum(e.kind == "tool_call" for e in events),
        "tool_result": sum(e.kind == "tool_result" for e in events),
        "user_text": sum((e.kind == "message" and e.role == "user") or e.kind == "interrupt" for e in events),
    }


def _rate(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def check(root: str | Path, baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Reader health for every transcript under a Claude Code projects root."""
    totals: Counter[str] = Counter()
    record_types: Counter[str] = Counter()
    block_types: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    mismatched: list[dict[str, Any]] = []
    files = transcripts(root)
    for path in files:
        raw = raw_scan(path)
        for key, value in raw.items():
            if isinstance(value, int):
                totals[key] += value
        record_types.update(raw.get("record_types", {}))
        block_types.update(raw.get("block_types", {}))
        versions.update(raw.get("versions", {}))
        seen = reader_counts(path)
        diff = {k: {"raw": raw.get(k, 0), "reader": v} for k, v in seen.items() if raw.get(k, 0) != v}
        if diff:
            mismatched.append({"transcript": path.name, "counts": diff})
    rates = {
        "parse_error_rate": _rate(totals["parse_errors"], totals["records"]),
        "missing_message_rate": _rate(totals["missing_message"], totals["conversation"]),
        "unknown_block_rate": _rate(totals["unknown_blocks"], totals["blocks"]),
        "unpaired_result_rate": _rate(totals["unpaired_results"], totals["tool_result"]),
        "conversation_share": _rate(totals["conversation"], totals["records"]),
        "origin_coverage": _rate(totals["typed_with_origin"], totals["typed"]),
        "usage_coverage": _rate(totals["assistant_with_usage"], totals["assistant"]),
    }
    signals = [
        {"id": key, "value": rates[key], "limit": LIMITS[key], "drift": rates[key] > LIMITS[key]}
        for key in ("parse_error_rate", "missing_message_rate", "unknown_block_rate", "unpaired_result_rate")
    ]
    # Records with no conversation at all means the reader would return nothing: drift at any size.
    # A low share needs MIN_RECORDS so one short bookkeeping-heavy transcript isn't flagged.
    low = ((totals["records"] >= MIN_RECORDS and rates["conversation_share"] < LIMITS["conversation_share_min"])
           or (totals["records"] > 0 and totals["conversation"] == 0))
    signals.append({"id": "conversation_share", "value": rates["conversation_share"],
                    "limit": LIMITS["conversation_share_min"], "drift": low})
    signals.append({"id": "reader_matches_raw", "value": len(mismatched), "limit": 0, "drift": bool(mismatched)})
    notes: dict[str, list[str]] = {}
    if baseline:
        for key in ("origin_coverage", "usage_coverage", "conversation_share"):
            before = (baseline.get("rates") or {}).get(key)
            if isinstance(before, (int, float)):
                dropped = before - rates[key] > BASELINE_MAX_DROP
                signals.append({"id": f"{key}_vs_baseline", "value": rates[key], "baseline": before,
                                "limit": f"no more than {BASELINE_MAX_DROP} below baseline", "drift": dropped})
        for name, now, before in (("record_types", record_types, baseline.get("record_types")),
                                  ("block_types", block_types, baseline.get("block_types")),
                                  ("versions", versions, baseline.get("versions"))):
            if isinstance(before, dict):
                new = sorted(set(now) - set(before))
                if new:
                    notes[f"new_{name}"] = new  # informational: new kinds are ignored safely, or need a fixture
    drift = [s["id"] for s in signals if s["drift"]]
    return {"schema": SCHEMA, "verdict": "drift" if drift else "ok", "drift": drift,
            "transcripts": len(files), "totals": {k: totals[k] for k in sorted(totals)}, "rates": rates,
            "signals": signals, "mismatched": mismatched[:20], "notes": notes,
            "record_types": dict(record_types), "block_types": dict(block_types), "versions": dict(versions)}


class ReaderDrift(Exception):
    """The reader may not see the transcripts as written; results built on it can't be trusted."""


def require_healthy(root: str | Path) -> dict[str, Any]:
    report = check(root)
    if report["verdict"] != "ok":
        raise ReaderDrift(
            f"reader_drift: {', '.join(report['drift'])}. Run `sessiongraph reader-health --claude-code {root}` "
            "for details; nothing was written. Pass --allow-drift to run anyway.")
    return report
