"""Aggregate agentctl failure tags into content-free failures.json / failures.md."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agentctl_jobs import (
    classify_jobs,
    enrich_with_remaps,
    iter_jobs,
    unknown_failure_classes,
)
from . import reader_health

SCHEMA = "sessiongraph.failures.v1"


def _bump(tree: dict[str, Any], tag: str, agent: str | None, model: str | None) -> None:
    lane = agent or "(none)"
    mod = model or "(none)"
    by_lane = tree.setdefault(tag, {})
    by_model = by_lane.setdefault(lane, {})
    by_model[mod] = int(by_model.get(mod, 0)) + 1


def aggregate(
    home: str | Path | None = None,
    *,
    since: datetime | None = None,
) -> dict[str, Any]:
    records = enrich_with_remaps(list(iter_jobs(home, since=since)), home)
    classified = classify_jobs(records)
    health = reader_health.check_agentctl(home, classified=classified)

    by_tag: dict[str, Any] = {}
    totals: Counter[str] = Counter()
    jobs_out: list[dict[str, Any]] = []

    for row in classified:
        tags = list(row.get("tags") or [])
        for tag in tags:
            totals[tag] += 1
            _bump(by_tag, tag, row.get("agent"), row.get("model"))
        jobs_out.append({
            "id": row.get("id"),
            "agent": row.get("agent"),
            "model": row.get("model"),
            "role": row.get("role"),
            "kind": row.get("kind"),
            "failureClass": row.get("failureClass"),
            "tags": tags,
            "legacy_relabel": bool(row.get("legacy_relabel")),
            "finished_at": row.get("finished_at"),
        })

    unknown = unknown_failure_classes(classified)
    doc = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": since.isoformat() if since else None,
        "agentctl_home": str(Path(home).expanduser() if home else Path.home() / ".agentctl"),
        "reader_health": health,
        "totals": {
            "jobs_seen": health["jobs_seen"],
            "results_parsed": health["results_parsed"],
            "unknown_failure_class": len(unknown),
            "provider_aup": int(totals.get("provider_aup", 0)),
            "usage_limit": int(totals.get("usage_limit", 0)),
            "policy_remap": int(totals.get("policy_remap", 0)),
            "legacy_relabel": int(totals.get("legacy_relabel", 0)),
        },
        "by_tag": by_tag,
        "jobs": jobs_out,
    }
    return doc


def render_markdown(doc: dict[str, Any]) -> str:
    totals = doc.get("totals") or {}
    lines = [
        "# SessionGraph failures",
        "",
        f"Generated: `{doc.get('generated_at')}`",
        f"Since: `{doc.get('since')}`",
        f"Home: `{doc.get('agentctl_home')}`",
        "",
        "## Totals",
        "",
        f"- jobs_seen: **{totals.get('jobs_seen', 0)}**",
        f"- results_parsed: **{totals.get('results_parsed', 0)}**",
        f"- provider_aup: **{totals.get('provider_aup', 0)}**",
        f"- usage_limit: **{totals.get('usage_limit', 0)}**",
        f"- policy_remap: **{totals.get('policy_remap', 0)}**",
        f"- legacy_relabel: **{totals.get('legacy_relabel', 0)}**",
        f"- unknown_failure_class: **{totals.get('unknown_failure_class', 0)}**",
        "",
        "## Reader health",
        "",
        f"```json\n{json.dumps(doc.get('reader_health') or {}, indent=2)}\n```",
        "",
        "## By tag × lane × model",
        "",
    ]
    by_tag = doc.get("by_tag") or {}
    for tag in sorted(by_tag):
        lines.append(f"### `{tag}`")
        for lane, models in sorted((by_tag[tag] or {}).items()):
            for model, n in sorted((models or {}).items()):
                lines.append(f"- {lane}/{model}: {n}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_bundle(doc: dict[str, Any], out: str | Path) -> Path:
    destination = Path(out).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "failures.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (destination / "failures.md").write_text(render_markdown(doc), encoding="utf-8")
    return destination
