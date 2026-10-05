"""Human-readable rationale for a suggested workflow."""

"""Deterministic session → suggested workflow compiler (suggest-map-v1)."""

from typing import Any

from .rules import MAPPING_VERSION, TopologyRule
from .select import _falsification, held_back

def render_rationale(plan: dict[str, Any], analysis: dict[str, Any]) -> str:
    lines = [
        "# Suggest-workflow rationale",
        "",
        f"- Mapping: `{MAPPING_VERSION}`",
        f"- Primary finding: `{plan.get('primary_finding') or 'healthy'}`",
        f"- Findings used: {', '.join(f'`{c}`' for c in plan.get('findings_used') or []) or '(none)'}",
        f"- Held back (unverified heuristic checks): "
        f"{', '.join(f'`{c}`' for c in held_back(list(analysis.get('findings') or []))) or '(none)'}",
        f"- Session workflow_health: **{(analysis.get('metrics') or {}).get('workflow_health', '?')}/100**",
        "",
        "## Applied rules",
        "",
    ]
    primary: TopologyRule = plan["primary_rule"]
    lines.extend([
        f"### Spine: `{primary.code}`",
        "",
        f"- Topology move: {primary.topology_move}",
        f"- Expected metric movement: {primary.expected_metric}",
        "",
    ])
    for rule in plan.get("guard_rules") or []:
        lines.extend([
            f"### Guard: `{rule.code}`",
            "",
            f"- Topology move: {rule.topology_move}",
            f"- Expected metric movement: {rule.expected_metric}",
            "",
        ])
    if plan.get("skipped"):
        lines.extend([
            "## Skipped",
            "",
            "No findings from trusted checks and `--include-healthy` was not set. No topology change suggested.",
            "",
        ])
    lines.extend([
        "## Experiment",
        "",
        "Re-run a comparable task with this workflow applied and verify the target metrics.",
        _falsification(plan),
        "Rollback: discard the artifact directory and restore the prior workflow.",
        "",
    ])
    return "\n".join(lines)
