"""Run the same fixed graph-reading task with vanilla and SessionGraph-assisted agentctl."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


EXPECTED = {
    "artifact_is_dag": True,
    "artifact_max_depth": 5,
    "artifact_components": 1,
    "artifact_request_output_coverage": 1.0,
    "artifact_changed_artifacts": 1,
    "artifact_verified_artifacts": 1,
    "cycle_is_dag": False,
    "cycle_cycle_nodes": 2,
    "cycle_implicit_nodes": 1,
    "disconnected_components": 2,
    "disconnected_request_output_coverage": 0.0,
    "failed_test_artifact_verification_coverage": 0.0,
}


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _answer(envelope: Any) -> dict[str, Any] | None:
    candidates = list(_strings(envelope))
    if isinstance(envelope, dict):
        candidates.insert(0, json.dumps(envelope))
    for text in reversed(candidates):
        stripped = text.strip()
        if stripped.startswith("```json") and stripped.endswith("```"):
            stripped = stripped[7:-3].strip()
        starts = [0] if stripped.startswith("{") else []
        starts.extend(index for index, char in enumerate(stripped) if char == "{")
        for start in starts:
            try:
                value, _ = json.JSONDecoder().raw_decode(stripped[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and set(EXPECTED).issubset(value):
                return {key: value.get(key) for key in EXPECTED}
    return None


def _run(prompt: str, session: str, timeout: int, cwd: Path) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        ["agentctl", "delegate", "--to", "codex", "--model", "gpt-5.6-luna",
         "--effort", "low", "--timeout", str(timeout), "--format", "json",
         "--session", session],
        input=prompt, text=True, capture_output=True, timeout=timeout + 15, cwd=cwd,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 3)
    try:
        envelope = json.loads(completed.stdout)
    except json.JSONDecodeError:
        envelope = None
    answer = _answer(envelope)
    contamination_markers = [
        marker for marker in ("run_agentctl_graph_bench.py", "EXPECTED =", str(Path(__file__).resolve().parents[1]))
        if marker in completed.stdout
    ]
    usage = None
    if isinstance(envelope, dict):
        usage = (((envelope.get("result") or {}).get("ask") or {}).get("usage"))
    checks = [{
        "id": key, "expected": expected, "observed": answer.get(key) if answer else None,
        "ok": bool(answer is not None and answer.get(key) == expected),
    } for key, expected in EXPECTED.items()]
    return {
        "command": "agentctl delegate --to codex --model gpt-5.6-luna --effort low",
        "session": session,
        "exit_code": completed.returncode,
        "elapsed_seconds": elapsed,
        "answer": answer,
        "usage": usage,
        "contaminated": bool(contamination_markers),
        "contamination_markers": contamination_markers,
        "passed": sum(item["ok"] for item in checks),
        "required": len(checks),
        "checks": checks,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--metrics-dir", required=True, type=Path,
                        help="Directory containing the four fixture graph-metrics.json outputs")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    root = Path(__file__).resolve().parent / "fixtures" / "networkx-bench"
    generated = args.metrics_dir.resolve()
    destination = Path(args.out).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sessiongraph-agentctl-bench-") as temporary:
        workspace = Path(temporary)
        vanilla_workspace = workspace / "vanilla"
        assisted_workspace = workspace / "assisted"
        raw = vanilla_workspace / "raw"
        assisted = assisted_workspace
        vanilla_workspace.mkdir()
        assisted_workspace.mkdir()
        raw.mkdir()
        shutil.copy2(project / "examples" / "artifact-lineage.jsonl", raw / "artifact-lineage.jsonl")
        for name in ("cycle", "disconnected", "failed-test"):
            shutil.copy2(root / f"{name}.jsonl", raw / f"{name}.jsonl")
        for name in ("artifact-lineage", "cycle", "disconnected", "failed-test"):
            target = assisted / name
            target.mkdir()
            shutil.copy2(generated / name / "graph-metrics.json", target / "graph-metrics.json")
        prompts = {
            "vanilla": (root / "vanilla-agentctl-prompt.md").read_text(encoding="utf-8"),
            "sessiongraph_assisted": (
                root / "sessiongraph-agentctl-prompt.md"
            ).read_text(encoding="utf-8"),
        }
        runs = {
            "vanilla": _run(
                prompts["vanilla"], "sg-graph-bench-vanilla-compact", args.timeout, vanilla_workspace
            ),
            "sessiongraph_assisted": _run(
                prompts["sessiongraph_assisted"], "sg-graph-bench-assisted-compact",
                args.timeout, assisted_workspace
            ),
        }
        for name, prompt in prompts.items():
            (destination / f"{name}.prompt.md").write_text(prompt, encoding="utf-8")
    result = {
        "schema_version": 1,
        "contract": "same model, effort, questions and answer key; SessionGraph outputs added only to assisted run",
        "model": "gpt-5.6-luna",
        "effort": "low",
        "expected": EXPECTED,
        "runs": runs,
        "delta": {
            "passed": runs["sessiongraph_assisted"]["passed"] - runs["vanilla"]["passed"],
            "elapsed_seconds": round(
                runs["sessiongraph_assisted"]["elapsed_seconds"] - runs["vanilla"]["elapsed_seconds"], 3
            ),
        },
        "limitations": [
            "one run per condition",
            "synthetic graphs",
            "elapsed time includes agent startup and local tool overhead",
            "does not measure human visualization comprehension or general coding quality",
        ],
    }
    (destination / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, run in runs.items():
        (destination / f"{name}.stdout.json").write_text(run["stdout"], encoding="utf-8")
        (destination / f"{name}.stderr.txt").write_text(run["stderr"], encoding="utf-8")
    print(json.dumps({
        name: {"passed": run["passed"], "required": run["required"],
               "elapsed_seconds": run["elapsed_seconds"], "exit_code": run["exit_code"]}
        for name, run in runs.items()
    }, indent=2, sort_keys=True))
    return 0 if all(
        run["exit_code"] == 0 and run["passed"] == run["required"] and not run["contaminated"]
        for run in runs.values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
