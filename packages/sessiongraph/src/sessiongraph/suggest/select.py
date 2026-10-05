"""Select trusted findings and map them to a workflow plan."""

"""Deterministic session → suggested workflow compiler (suggest-map-v1)."""

from typing import Any

from .rules import HEALTHY_RULE, MAPPING, SEVERITY_RANK, SPINE_PRIORITY

def trusted(code: Any) -> bool:
    """A finding may drive a recommendation only when its check is a recorded fact or verified."""
    from ..analyze import CHECKS
    from .rules import VERIFIED_HEURISTICS

    spec = CHECKS.get(str(code))
    return code in VERIFIED_HEURISTICS or (spec is not None and spec[2] == "definition")


def held_back(findings: list[dict[str, Any]]) -> list[str]:
    """Mapped findings that were not used because their check is unverified."""
    return sorted({str(f.get("code")) for f in findings if f.get("code") in MAPPING and not trusted(f.get("code"))})


def select_findings(
    findings: list[dict[str, Any]],
    *,
    max_findings: int = 3,
) -> list[dict[str, Any]]:
    """Trusted findings only, severity-ranked, then spine priority, capped by max_findings."""
    known = [f for f in findings if f.get("code") in MAPPING and trusted(f.get("code"))]
    known.sort(
        key=lambda f: (
            SEVERITY_RANK.get(str(f.get("severity", "info")), 9),
            SPINE_PRIORITY.get(str(f.get("code")), 99),
            str(f.get("code")),
        )
    )
    return known[: max(0, max_findings)]


def map_topology(selected: list[dict[str, Any]]) -> dict[str, Any]:
    """Compose one primary spine + guards from selected findings."""
    if not selected:
        return {
            "primary_finding": None,
            "primary_rule": HEALTHY_RULE,
            "guard_rules": [],
            "findings_used": [],
            "skipped": False,
            "healthy": True,
        }

    spine_candidates = [f for f in selected if MAPPING[str(f.get("code"))].role == "spine"]
    if spine_candidates:
        spine_candidates.sort(
            key=lambda f: (
                SEVERITY_RANK.get(str(f.get("severity", "info")), 9),
                SPINE_PRIORITY.get(str(f.get("code")), 99),
                str(f.get("code")),
            )
        )
        primary = spine_candidates[0]
    else:
        primary = selected[0]
    primary_rule = MAPPING[primary["code"]]

    guards: list[TopologyRule] = []
    for finding in selected:
        if finding["code"] == primary["code"]:
            continue
        # Secondary findings always contribute as guards (even if spine-capable).
        guards.append(MAPPING[finding["code"]])

    return {
        "primary_finding": primary["code"],
        "primary_rule": primary_rule,
        "guard_rules": guards,
        "findings_used": [f["code"] for f in selected],
        "skipped": False,
        "healthy": False,
        "selected_findings": selected,
    }


def _falsification(plan: dict[str, Any]) -> str:
    if {"loop_incomplete", "loop_telemetry_gap"} & set(plan.get("findings_used") or []):
        return ("Falsify if terminal capture or failure classification remains missing on fixed replays. "
                "Newly exposed failures may lower health; verify capture and task outcomes independently.")
    return "Falsify if workflow_health drops or new user_correction/errors appear."
