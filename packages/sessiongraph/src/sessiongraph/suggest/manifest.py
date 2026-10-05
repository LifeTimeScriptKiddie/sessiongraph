"""Suggest-workflow manifest.json builder."""

"""Deterministic session → suggested workflow compiler (suggest-map-v1)."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .rules import MAPPING_VERSION, SCHEMA_VERSION

def build_manifest(
    *,
    target: str,
    plan: dict[str, Any],
    source: Path,
    task: str,
    out: Path,
    skipped: bool,
    held: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "held_back_unverified": list(held or []),
        "schema_version": SCHEMA_VERSION,
        "mapping_version": MAPPING_VERSION,
        "target": target,
        "primary_finding": plan.get("primary_finding"),
        "findings_used": list(plan.get("findings_used") or []),
        "source": str(source),
        "task": task,
        "out": str(out),
        "skipped": skipped,
        "healthy_template": bool(plan.get("healthy")),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
