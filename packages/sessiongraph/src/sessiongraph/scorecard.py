"""Compare scorecard: numeric pass/fail gates on baseline → candidate analyses.

Accuracy here means measurable health/finding improvement after following a suggested
topology — not LLM taste and not answer correctness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analyze import compare

SCORECARD_VERSION = "suggest-scorecard-v2"
SCHEMA_VERSION = 1

# Default gates match RUN-SPEC: health up, findings down or flat, no new dangling_edges.
DEFAULT_GATES: dict[str, Any] = {
    "min_workflow_health_delta": 1,
    "max_finding_delta": 0,
    "forbid_new_dangling_edges": True,
    "forbid_new_critical_findings": True,
}


def _finding_codes(analysis: dict[str, Any]) -> list[str]:
    return [str(item.get("code")) for item in analysis.get("findings") or [] if item.get("code")]


def _codes_by_severity(analysis: dict[str, Any], severity: str) -> set[str]:
    return {
        str(item.get("code"))
        for item in analysis.get("findings") or []
        if item.get("code") and str(item.get("severity")) == severity
    }


def evaluate_scorecard(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    gates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a scorecard dict with ``ok`` and per-gate results."""
    active = {**DEFAULT_GATES, **(gates or {})}
    comparison = compare(before, after)
    delta = comparison.get("delta") or {}
    health_delta = int(delta.get("workflow_health") or 0)
    finding_delta = int(comparison.get("finding_delta") or 0)

    before_codes = set(_finding_codes(before))
    after_codes = set(_finding_codes(after))
    new_dangling = "dangling_edges" in after_codes and "dangling_edges" not in before_codes
    before_critical = _codes_by_severity(before, "critical")
    after_critical = _codes_by_severity(after, "critical")
    new_critical = sorted(after_critical - before_critical)

    gate_rows: list[dict[str, Any]] = []

    # Health improvement cannot compensate for missing loop evidence. Requiring
    # explicit metrics also fails closed for old analyses: re-analyze their traces.
    if any(item.get("session", {}).get("format") == "agentctl-loop-v1" for item in (before, after)):
        evidence_ok = all(
            item.get("session", {}).get("format") == "agentctl-loop-v1"
            and item.get("metrics", {}).get("loop_terminal_recorded") is True
            and item.get("metrics", {}).get("loop_failure_classification_missing") == 0
            for item in (before, after)
        )
        gate_rows.append({
            "id": "agentctl_evidence_available", "ok": evidence_ok,
            "observed": evidence_ok,
            "required": "both traces have recognized terminal records and classified stage failures; re-analyze legacy exports",
        })

    min_health = int(active["min_workflow_health_delta"])
    gate_rows.append({
        "id": "workflow_health_delta",
        "ok": health_delta >= min_health,
        "observed": health_delta,
        "required": f">= {min_health}",
    })

    max_findings = int(active["max_finding_delta"])
    gate_rows.append({
        "id": "finding_delta",
        "ok": finding_delta <= max_findings,
        "observed": finding_delta,
        "required": f"<= {max_findings}",
    })

    if active.get("forbid_new_dangling_edges"):
        gate_rows.append({
            "id": "no_new_dangling_edges",
            "ok": not new_dangling,
            "observed": new_dangling,
            "required": False,
        })

    if active.get("forbid_new_critical_findings"):
        gate_rows.append({
            "id": "no_new_critical_findings",
            "ok": not new_critical,
            "observed": new_critical,
            "required": [],
        })

    ok = all(row["ok"] for row in gate_rows)
    failed_gates = [row["id"] for row in gate_rows if not row["ok"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "scorecard_version": SCORECARD_VERSION,
        "ok": ok,
        "failed_gates": failed_gates,
        "gates": gate_rows,
        "compare": comparison,
        "before_finding_codes": sorted(before_codes),
        "after_finding_codes": sorted(after_codes),
        "summary": (
            f"{'PASS' if ok else 'FAIL'}: health_delta={health_delta}, "
            f"finding_delta={finding_delta}, new_critical={new_critical or '[]'}, failed_gates={failed_gates}"
        ),
    }


def load_analysis_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "findings" not in data or "metrics" not in data:
        raise ValueError(f"malformed analysis.json: {path}")
    return data


def scorecard_from_paths(
    before: Path,
    after: Path,
    *,
    gates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return evaluate_scorecard(load_analysis_json(before), load_analysis_json(after), gates=gates)
