"""CLI + helper coverage for SessionGraph ↔ iseeagents eventId join."""

from __future__ import annotations

import json
from pathlib import Path

from sessiongraph.cli import main
from sessiongraph.iseeagents_join import join_analysis_to_provenance, load_iseeagents_jsonl


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "iseeagents_join"


def _write_fixture(tmp: Path) -> tuple[Path, Path]:
    provenance = [
        {
            "schemaVersion": "iseeagents.context.v1",
            "eventId": "evt-a",
            "sessionId": "sess-1",
            "requestId": "req-1",
            "observation": "load",
            "evidence": "observed",
            "coverage": "partial",
            "boundary": "adapter",
            "adapterId": "pi",
        },
        {
            "schemaVersion": "iseeagents.context.v1",
            "eventId": "evt-b",
            "sessionId": "sess-1",
            "requestId": None,
            "observation": "usage",
            "evidence": "observed",
            "coverage": "partial",
            "boundary": "adapter",
            "adapterId": "pi",
        },
        {
            "schemaVersion": "other",
            "eventId": "evt-skip",
        },
    ]
    analysis = {
        "events": [{"id": "evt-a"}],
        "graph": {"nodes": [{"id": "evt-b"}, {"id": "evt-missing"}]},
    }
    prov_path = tmp / "prov.jsonl"
    analysis_path = tmp / "analysis.json"
    prov_path.write_text("\n".join(json.dumps(row) for row in provenance) + "\n", encoding="utf-8")
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    return analysis_path, prov_path


def test_join_helper_matches_on_event_id(tmp_path: Path) -> None:
    analysis_path, prov_path = _write_fixture(tmp_path)
    hits = join_analysis_to_provenance(
        json.loads(analysis_path.read_text(encoding="utf-8")),
        load_iseeagents_jsonl(prov_path),
    )
    assert [h["eventId"] for h in hits] == ["evt-a", "evt-b"]
    assert hits[0]["observation"] == "load"
    assert hits[1]["adapterId"] == "pi"


def test_join_iseeagents_cli_writes_payload(tmp_path: Path) -> None:
    analysis_path, prov_path = _write_fixture(tmp_path)
    out = tmp_path / "join.json"
    assert main(["join-iseeagents", str(analysis_path), str(prov_path), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["provenance_events"] == 2
    assert payload["joined"] == 2
    assert {h["eventId"] for h in payload["hits"]} == {"evt-a", "evt-b"}
