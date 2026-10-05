"""Topology fingerprints for golden fixtures and scorecard-adjacent checks."""

"""Deterministic session → suggested workflow compiler (suggest-map-v1)."""

import json
from hashlib import sha256
from typing import Any

from .rules import HEALTHY_RULE, MAPPING_VERSION
from .render import _plan_flags, _pi_meta_name, _pi_phases, render_markdown, render_pi_js
from .select import map_topology, select_findings

def topology_snapshot(
    analysis: dict[str, Any],
    *,
    max_findings: int = 3,
    include_healthy: bool = False,
) -> dict[str, Any]:
    """Content-free topology fingerprint for golden fixtures and determinism checks."""
    selected = select_findings(list(analysis.get("findings") or []), max_findings=max_findings)
    if not selected and not include_healthy:
        return {
            "mapping_version": MAPPING_VERSION,
            "skipped": True,
            "primary_finding": None,
            "findings_used": [],
            "guard_codes": [],
            "flags": {},
            "pi_phases": [],
            "markdown_graph": None,
            "pi_meta_name": None,
        }

    if not selected and include_healthy:
        plan: dict[str, Any] = {
            "primary_finding": None,
            "primary_rule": HEALTHY_RULE,
            "guard_rules": [],
            "findings_used": [],
            "skipped": False,
            "healthy": True,
        }
    else:
        plan = map_topology(selected)

    flags = _plan_flags(plan)
    phases = _pi_phases(plan, flags)
    markdown = render_markdown(plan, task="fixture")
    graph_line = next((line.strip() for line in markdown.splitlines() if "→" in line), None)
    pi_js = render_pi_js(plan, task="fixture")
    meta_name = None
    for line in pi_js.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            # name: "sg_…"
            raw = stripped.split(":", 1)[1].strip().rstrip(",")
            meta_name = json.loads(raw)
            break
    return {
        "mapping_version": MAPPING_VERSION,
        "skipped": False,
        "primary_finding": plan.get("primary_finding"),
        "findings_used": list(plan.get("findings_used") or []),
        "guard_codes": [rule.code for rule in plan.get("guard_rules") or []],
        "flags": flags,
        "pi_phases": phases,
        "markdown_graph": graph_line,
        "pi_meta_name": meta_name,
    }


def topology_digest(snapshot: dict[str, Any]) -> str:
    """Stable digest of a topology snapshot (excludes nothing mutable — snapshot is already content-free)."""
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()
