from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

from .model import Session


def _mermaid_id(value: str) -> str:
    return "n_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _mermaid_label(value: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    return html.escape(value, quote=True)[:120]


def mermaid(analysis: dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    for node in analysis["graph"]["nodes"]:
        label = _mermaid_label(": ".join(part for part in (node["kind"], node.get("name")) if part))
        lines.append(f'  {_mermaid_id(node["id"])}["{label}"]')
    for edge in analysis["graph"]["edges"]:
        lines.append(f'  {_mermaid_id(edge["from"])} --> {_mermaid_id(edge["to"])}')
    return "\n".join(lines) + "\n"


def markdown(analysis: dict[str, Any]) -> str:
    session, metrics = analysis["session"], analysis["metrics"]
    lines = [
        "# SessionGraph report", "",
        f"- Session: `{session['id']}`", f"- Format: `{session['format']}`",
        f"- Workflow health: **{metrics['workflow_health']}/100**",
        f"- Events / tool calls / branches: {metrics['events']} / {metrics['tool_calls']} / {metrics['branches']}",
        "", "## Findings", "",
    ]
    if "loop_iterations" in metrics:
        lines[4:4] = [
            f"- Loop iterations / retries / status: {metrics['loop_iterations']} / "
            f"{metrics['loop_retries']} / `{metrics.get('loop_status') or 'unknown'}`",
            f"- Recorded agent time: {metrics['loop_duration_ms']} ms "
            f"({', '.join(f'{name}: {duration} ms' for name, duration in metrics['loop_stage_duration_ms'].items())})",
        ]
    if "retrieval_attempts" in metrics:
        lines[4:4] = [
            f"- Retrieval attempts / unsuccessful: {metrics['retrieval_attempts']} / {metrics['retrieval_unsuccessful_attempts']}",
            f"- Recorded retrieval time: {metrics['retrieval_elapsed_s']} s; success: {bool(metrics['retrieval_success'])}",
        ]
    if not analysis["findings"]:
        lines.append("No deterministic loop or dead-end signals were detected.")
    for finding in analysis["findings"]:
        lines.extend([
            f"### {finding['severity'].upper()}: {finding['summary']} (`{finding['code']}`)", "",
            f"Evidence event IDs: {', '.join(f'`{item}`' for item in finding['evidence'])}", "",
            f"Recommendation: {finding['recommendation']}", "",
        ])
    lines.extend([
        "## Improvement loop", "",
        "1. Choose one finding and write a falsifiable workflow change.",
        "2. Run comparable tasks with the baseline and candidate workflow.",
        "3. Analyze both sessions and use `sessiongraph compare`.",
        "4. Keep the change only when the target metric improves without a regression in errors or user corrections.",
        "", "## Interaction graph", "", "```mermaid", mermaid(analysis).rstrip(), "```", "",
        "Content is omitted by default; evidence uses event IDs and stable fingerprints.", "",
    ])
    return "\n".join(lines)


def write_bundle(session: Session, analysis: dict[str, Any], destination: Path, include_content: bool) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    export = dict(analysis)
    export["events"] = [event.public(include_content=include_content) for event in session.events]
    (destination / "analysis.json").write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (destination / "report.md").write_text(markdown(analysis), encoding="utf-8")
    (destination / "graph.mmd").write_text(mermaid(analysis), encoding="utf-8")
