"""Load analysis inputs for suggest-workflow."""

"""Deterministic session → suggested workflow compiler (suggest-map-v1)."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..analyze import analyze
from ..parsers import load_session

def _task_label(task: str | None, analysis: dict[str, Any]) -> str:
    if task and task.strip():
        return task.strip()[:200]
    session = analysis.get("session") or {}
    sid = session.get("id") or "session"
    return f"(from session {sid})"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_out_dir(target: str, cwd: Path | None = None) -> Path:
    root = cwd or Path.cwd()
    return (root / ".sessiongraph" / f"suggest-{target}-{_utc_stamp()}").resolve()


def load_analysis(source: Path) -> dict[str, Any]:
    """Load analysis.json, report dir, or session JSONL."""
    path = source.expanduser().resolve()
    if not path.exists():
        raise ValueError(f"path not found: {path}")

    if path.is_dir():
        analysis_path = path / "analysis.json"
        if not analysis_path.is_file():
            raise ValueError(f"report directory missing analysis.json: {path}")
        return json.loads(analysis_path.read_text(encoding="utf-8"))

    if path.suffix == ".json" or path.name == "analysis.json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "findings" not in data or "metrics" not in data:
            raise ValueError("malformed analysis.json: need findings and metrics")
        return data

    # Session JSONL (or other session formats load_session accepts).
    session = load_session(path)
    return analyze(session)
