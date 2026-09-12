"""Fixed structural-coverage benchmark for the optional NetworkX adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sessiongraph.analyze import analyze
from sessiongraph.graph_metrics import measure_graph
from sessiongraph.parsers import parse_generic


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "artifact-lineage.jsonl"


def _session(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return analyze(parse_generic(rows, Path(name)))


def _get(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def main() -> int:
    artifact = analyze(parse_generic(
        [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()], FIXTURE
    ))
    cycle = _session([
        {"id": "a", "parent_ids": ["b"]},
        {"id": "b", "parent_ids": ["a", "missing"]},
    ], "cycle.jsonl")
    disconnected = _session([
        {"id": "request", "kind": "user_request", "parent_ids": []},
        {"id": "run", "parent_ids": ["request"]},
        {"id": "response", "kind": "final_response", "parent_ids": []},
    ], "disconnected.jsonl")
    failed_test = _session([
        {"id": "request", "kind": "user_request", "parent_ids": []},
        {"id": "run", "parent_ids": ["request"]},
        {"id": "artifact", "kind": "artifact", "parent_ids": ["run"],
         "parent_relations": {"run": "modified"}},
        {"id": "test", "kind": "test_run", "is_error": True, "parent_ids": ["artifact"],
         "parent_relations": {"artifact": "verified_by"}},
    ], "failed-test.jsonl")

    cases = {
        "artifact": artifact,
        "cycle": cycle,
        "disconnected": disconnected,
        "failed_test": failed_test,
    }
    baseline = {name: {"metrics": value["metrics"]} for name, value in cases.items()}
    candidate = {name: {
        "metrics": value["metrics"],
        "graph_metrics": measure_graph(value)["metrics"],
    } for name, value in cases.items()}
    checks = [
        ("core_edges", "artifact.metrics.edges", 8),
        ("core_merges", "artifact.metrics.merge_events", 3),
        ("core_branches", "artifact.metrics.branches", 1),
        ("artifact_dag", "artifact.graph_metrics.is_directed_acyclic", True),
        ("artifact_depth", "artifact.graph_metrics.max_depth", 5),
        ("artifact_components", "artifact.graph_metrics.weakly_connected_components", 1),
        ("artifact_request_coverage", "artifact.graph_metrics.request_output_coverage", 1.0),
        ("artifact_verification_coverage", "artifact.graph_metrics.artifact_verification_coverage", 1.0),
        ("artifact_relation_types", "artifact.graph_metrics.relation_counts.modified", 1),
        ("cycle_detected", "cycle.graph_metrics.is_directed_acyclic", False),
        ("cycle_nodes", "cycle.graph_metrics.cycle_nodes", 2),
        ("cycle_missing_parent", "cycle.graph_metrics.implicit_nodes", 1),
        ("cycle_depth_suppressed", "cycle.graph_metrics.max_depth", None),
        ("disconnected_components", "disconnected.graph_metrics.weakly_connected_components", 2),
        ("unreachable_output", "disconnected.graph_metrics.reachable_outputs", 0),
        ("zero_request_coverage", "disconnected.graph_metrics.request_output_coverage", 0.0),
        ("failed_test_changed", "failed_test.graph_metrics.changed_artifacts", 1),
        ("failed_test_not_verified", "failed_test.graph_metrics.verified_artifacts", 0),
        ("failed_test_zero_coverage", "failed_test.graph_metrics.artifact_verification_coverage", 0.0),
    ]

    def evaluate(subject: dict[str, Any]) -> dict[str, Any]:
        rows = []
        for check_id, path, expected in checks:
            observed = _get(subject, path)
            rows.append({
                "id": check_id, "path": path, "expected": expected,
                "observed": observed, "ok": observed == expected,
            })
        return {"passed": sum(row["ok"] for row in rows), "required": len(rows), "checks": rows}

    payload = {
        "schema_version": 1,
        "contract": "fixed structural capability checks; same parsed graphs for baseline and candidate",
        "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "baseline": evaluate(baseline),
        "candidate": evaluate(candidate),
        "claims_excluded": [
            "answer correctness", "model reasoning or attention", "human comprehension", "runtime speedup",
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["candidate"]["passed"] == payload["candidate"]["required"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
