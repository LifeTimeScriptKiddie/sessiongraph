"""Codify a mined workflow family as one portable SKILL.md (the baseline version).

One file is the source of truth. Claude Code, Codex, Cursor and Pi all load
Agent Skills folders (`<dir>/<name>/SKILL.md`), so `install` links that one
folder into each tool's skills directory instead of copying it: an edit from
any tool changes the same file, and there is one version to measure.

The skill's steps come from the family's definition (what makes a request
`ship:edit-test`), not from the mined typical path: the greedy typical path
drops edit and test on long, varied shapes. Mined numbers supply the evidence
and the stop rules. Nothing here calls a model.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA = "sessiongraph.codify.v1"

# Skills directories of the tools that load Agent Skills.
SKILL_DIRS = {
    "claude-code": "~/.claude/skills",
    "codex": "~/.codex/skills",
    "cursor": "~/.cursor/skills",
    "pi": "~/.pi/agent/skills",
}

# Steps per family kind. Each step names the phase it maps to, so a later run can check the order held.
TEMPLATES: dict[str, dict[str, Any]] = {
    "ship:edit-test": {
        "description": (
            "Make a code change and ship it: edit, verify with the repo's own tests or build, then commit. "
            "Use when a request changes code and ends in a commit. Not for config-only or script-only changes, "
            "or for committing work that already exists."
        ),
        "title": "Ship a code change: edit, test, commit",
        "steps": [
            ("explore", "Find the code to change and the repo's own check: the test or build command its README, "
                        "package.json, Makefile or CI config uses. Write the check command down before editing."),
            ("test", "Run that check once before editing, so you know which failures were already there."),
            ("edit", "Make the change. Keep it to what the request asks."),
            ("test", "Run the same check again. It must pass, or fail only where it failed before the edit."),
            ("commit", "Commit only after that check. One commit for this request, with a message that says what changed and why."),
        ],
        "rules": [
            "No commit before a passing check that ran after the last edit. If you edit again, run the check again.",
            "Stop rule: if the same command fails twice in a row, do not run it a third time. "
            "Say what failed, form a new hypothesis, and change the approach, or ask the user.",
            "A shell command that fails because of the environment (a missing tool, wrong folder or path) is fixed or reported "
            "before anything else, not worked around.",
            "Do not push, publish or deploy as part of this workflow unless the user asks.",
        ],
        "report": ["Files changed", "The check command and its result (before and after the edit)", "The commit hash"],
    },
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")


def _family(doc: dict[str, Any], name: str) -> dict[str, Any]:
    for fam in doc.get("families", []):
        if fam.get("family") == name:
            return fam
    raise ValueError(f"no family '{name}' in the workflows document")


def render_skill(fam: dict[str, Any], skill_name: str, baseline_ref: str) -> str:
    base = fam.get("base_family", fam["family"])
    template = TEMPLATES.get(base)
    if template is None:
        raise ValueError(f"no skill template for '{base}' yet (have: {', '.join(sorted(TEMPLATES))})")
    failing = ", ".join(f"{k} {v}" for k, v in list((fam.get("error_phases") or {}).items())[:3]) or "none"
    lines = [
        "---",
        f"name: {skill_name}",
        f"description: {json.dumps(template['description'])}",  # quoted: the text has colons
        "---",
        "",
        f"# {template['title']}",
        "",
        "## Steps",
        "",
        *[f"{i}. **{phase}**: {text}" for i, (phase, text) in enumerate(template["steps"], 1)],
        "",
        "## Rules",
        "",
        *[f"- {rule}" for rule in template["rules"]],
        "",
        "## Report when done",
        "",
        *[f"- {item}" for item in template["report"]],
        "",
        "## Why this skill exists",
        "",
        f"Mined by SessionGraph from `{fam['family']}` before this skill existed: {fam['requests']} requests in "
        f"{fam['sessions']} sessions over {fam['days']} days. {round(fam.get('friction_rate', 0) * 100)}% of runs had a "
        f"step other than a test fail (most: {failing}); median {fam.get('median_steps')} steps; "
        f"{fam.get('variant_count')} different step orders. Baseline: `{baseline_ref}`.",
        "",
        f"This is the baseline version. Change it only after `sessiongraph workflows-compare` "
        f"gives a verdict on it, so the measurement means something.",
        "",
    ]
    return "\n".join(lines)


def codify(doc: dict[str, Any], family: str, out_root: Path, skill_name: str | None = None,
           baseline_path: Path | None = None) -> dict[str, Any]:
    """Write <out_root>/<skill>/SKILL.md and provenance.json; refuse to overwrite an existing skill."""
    fam = _family(doc, family)
    baseline_path = baseline_path.expanduser().resolve() if baseline_path else None
    name = skill_name or _slug(fam.get("base_family", family).replace(":", "-"))
    folder = out_root.expanduser() / name
    if (folder / "SKILL.md").exists():
        raise ValueError(f"{folder / 'SKILL.md'} exists; this baseline is edited by hand from here, not regenerated")
    baseline_ref = baseline_path.name if baseline_path else "(workflows document)"
    body = render_skill(fam, name, baseline_ref)
    rec = fam.get("recommendation") or {}
    after_family = f"skill:{name}"
    provenance = {
        "schema": SCHEMA,
        "skill": name,
        "family": family,
        "generated": date.today().isoformat(),
        "baseline": str(baseline_path) if baseline_path else None,
        "baseline_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest() if baseline_path else None,
        "recommendation": rec.get("id"),
        "metric": rec.get("metric"),
        "guard": rec.get("guard"),
        # once the skill is used, its requests are anchored to it and leave the mined family
        "after_family": after_family,
        "compare": (f"sessiongraph workflows-compare {baseline_path or 'before.json'} after/workflows.json "
                    f"--recommendation {rec.get('id')} --after-family {after_family}") if rec.get("id") else None,
        "skill_sha256": hashlib.sha256(body.encode()).hexdigest(),
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(body, encoding="utf-8")
    (folder / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return {"folder": str(folder), **provenance}


def install(folder: Path, dirs: dict[str, str] = SKILL_DIRS) -> dict[str, str]:
    """Link one skill folder into each tool's skills directory. Never replaces something else."""
    folder = folder.expanduser().resolve()
    result: dict[str, str] = {}
    for tool, raw in dirs.items():
        root = Path(raw).expanduser()
        link = root / folder.name
        if link.is_symlink() and link.resolve() == folder:
            result[tool] = "already linked"
            continue
        if link.exists() or link.is_symlink():
            result[tool] = f"skipped: {link} exists and is not this skill"
            continue
        root.mkdir(parents=True, exist_ok=True)
        link.symlink_to(folder, target_is_directory=True)
        result[tool] = f"linked {link}"
    return result
