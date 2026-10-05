"""Orchestrate suggest-workflow artifact writes."""

"""Deterministic session → suggested workflow compiler (suggest-map-v1)."""

import json
from pathlib import Path

from .io import _task_label, default_out_dir, load_analysis
from .manifest import build_manifest
from .rationale import render_rationale
from .render import render_agentctl, render_claude_js, render_markdown, render_pi_js
from .rules import HEALTHY_RULE
from .select import held_back, map_topology, select_findings

def suggest_workflow(
    source: Path,
    *,
    target: str,
    out: Path,
    task: str | None = None,
    max_findings: int = 3,
    include_healthy: bool = False,
) -> Path:
    """Write suggest-workflow artifacts under ``out``. Returns ``out``."""
    if target not in {"claude", "agentctl", "markdown", "pi"}:
        raise ValueError(f"unsupported target: {target}")

    source = source.expanduser().resolve()
    analysis = load_analysis(source)
    selected = select_findings(list(analysis.get("findings") or []), max_findings=max_findings)
    held = held_back(list(analysis.get("findings") or []))
    label = _task_label(task, analysis)
    out = out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Provenance: always persist the analysis used for the suggestion.
    (out / "analysis.json").write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not selected and not include_healthy:
        plan = {
            "primary_finding": None,
            "primary_rule": HEALTHY_RULE,
            "guard_rules": [],
            "findings_used": [],
            "skipped": True,
            "healthy": True,
        }
        manifest = build_manifest(
            target=target, plan=plan, source=source, task=label, out=out, skipped=True, held=held,
        )
        (out / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        (out / "rationale.md").write_text(render_rationale(plan, analysis), encoding="utf-8")
        (out / "SKIPPED.md").write_text(
            "# No suggestion\n\nSession has no mapped findings from trusted checks. "
            + (f"Held back because their checks are unverified heuristics: {', '.join(held)}. " if held else "")
            + "Pass `--include-healthy` for a linear template.\n",
            encoding="utf-8",
        )
        return out

    plan = map_topology(selected)
    if not selected and include_healthy:
        plan = {
            "primary_finding": None,
            "primary_rule": HEALTHY_RULE,
            "guard_rules": [],
            "findings_used": [],
            "skipped": False,
            "healthy": True,
        }

    manifest = build_manifest(
        target=target, plan=plan, source=source, task=label, out=out, skipped=False, held=held,
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    (out / "rationale.md").write_text(render_rationale(plan, analysis), encoding="utf-8")
    (out / "workflow.md").write_text(render_markdown(plan, task=label), encoding="utf-8")

    if target == "claude":
        (out / "workflow.js").write_text(render_claude_js(plan, task=label), encoding="utf-8")
    elif target == "pi":
        (out / "workflow.js").write_text(render_pi_js(plan, task=label), encoding="utf-8")
    elif target == "agentctl":
        task_md, run_yaml, rubric_md = render_agentctl(plan, task=label, analysis=analysis)
        (out / "task.md").write_text(task_md, encoding="utf-8")
        (out / "run.yaml").write_text(run_yaml, encoding="utf-8")
        (out / "rubric.md").write_text(rubric_md, encoding="utf-8")

    return out
