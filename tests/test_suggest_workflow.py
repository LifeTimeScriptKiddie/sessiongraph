"""Acceptance tests for sessiongraph suggest-workflow (suggest-map-v1)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sessiongraph.cli import main
from sessiongraph.suggest import MAPPING_VERSION, map_topology, select_findings, suggest_workflow


FIXTURE_ANALYSIS = {
    "schema_version": 1,
    "session": {"id": "fixture-suggest", "format": "pi-v3", "source": "fixture.jsonl", "metadata": {}},
    "metrics": {"workflow_health": 76, "tool_calls": 4, "events": 8, "branches": 0},
    "findings": [
        {
            "code": "repeated_action",
            "severity": "warning",
            "summary": "Repeated tool action 3 times",
            "evidence": ["t1", "t2", "t3"],
            "recommendation": "Add retry budget",
        },
        {
            "code": "errors",
            "severity": "warning",
            "summary": "1 unrecovered error",
            "evidence": ["r3"],
            "recommendation": "Classify before retry",
        },
    ],
    "graph": {"nodes": [], "edges": []},
}


class SuggestWorkflowTests(unittest.TestCase):
    def _write_analysis(self, directory: Path, body: dict | None = None) -> Path:
        path = directory / "analysis.json"
        path.write_text(json.dumps(body or FIXTURE_ANALYSIS, indent=2) + "\n", encoding="utf-8")
        return path

    def test_markdown_target(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root)
            out = root / "out-md"
            self.assertEqual(
                main(["suggest-workflow", str(analysis), "--target", "markdown", "--out", str(out)]),
                0,
            )
            workflow = (out / "workflow.md").read_text(encoding="utf-8")
            self.assertIn("RetryBudget", workflow)
            self.assertIn("`repeated_action`", workflow)
            # Guards must be whole lines, not character-iterated strings.
            self.assertIn("- ClassifyFailure before any Retry", workflow)
            self.assertNotIn("\n- C\n- l\n- a\n", workflow)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mapping_version"], MAPPING_VERSION)
            self.assertEqual(manifest["mapping_version"], "suggest-map-v1")
            self.assertIn("repeated_action", manifest["findings_used"])
            self.assertTrue((out / "rationale.md").is_file())
            self.assertTrue((out / "analysis.json").is_file())

    def test_pi_target(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root)
            out = root / "out-pi"
            self.assertEqual(
                main(["suggest-workflow", str(analysis), "--target", "pi", "--out", str(out)]),
                0,
            )
            js = (out / "workflow.js").read_text(encoding="utf-8")
            self.assertTrue(js.lstrip().startswith("export const meta"))
            self.assertIn("name:", js)
            self.assertIn("description:", js)
            self.assertIn("agent(", js)
            self.assertIn("phase(", js)
            self.assertIn("budget", js)
            self.assertNotIn("export async function run", js)
            self.assertNotIn("PLEASE_PASTE_MY_SECRET_PROMPT", js)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["target"], "pi")
            self.assertEqual(manifest["mapping_version"], MAPPING_VERSION)

    def test_pi_meta_name_from_primary_finding(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root)
            out = root / "out"
            suggest_workflow(analysis, target="pi", out=out, task="fix the loop")
            js = (out / "workflow.js").read_text(encoding="utf-8")
            # Fixture primary is errors (spine priority over repeated_action).
            self.assertIn('name: "sg_errors_repair"', js)
            self.assertIn("const task = (args && args.task)", js)
            self.assertIn("fix the loop", js)

    def test_pi_does_not_embed_transcript_text(self):
        body = dict(FIXTURE_ANALYSIS)
        body["findings"] = [
            {
                "code": "dead_end",
                "severity": "warning",
                "summary": "user said PLEASE_PASTE_MY_SECRET_PROMPT into the tool",
                "evidence": ["e1"],
                "recommendation": "handoff",
            }
        ]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root, body)
            out = root / "out"
            suggest_workflow(analysis, target="pi", out=out)
            js = (out / "workflow.js").read_text(encoding="utf-8")
            self.assertNotIn("PLEASE_PASTE_MY_SECRET_PROMPT", js)
            self.assertIn('name: "sg_dead_end_repair"', js)
            self.assertIn("terminal handoff", js)

    def test_pi_pipeline_contract_phases(self):
        body = {
            "schema_version": 1,
            "session": {"id": "pipe", "format": "pipeline", "source": "x", "metadata": {}},
            "metrics": {
                "workflow_health": 28,
                "pipeline_success": 0,
                "pipeline_checks_missing": 1,
                "tool_calls": 0,
                "events": 0,
                "branches": 0,
            },
            "findings": [
                {
                    "code": "pipeline_contract",
                    "severity": "critical",
                    "summary": "missing final-report",
                    "evidence": ["final-report"],
                    "recommendation": "restore producer",
                }
            ],
            "graph": {"nodes": [], "edges": []},
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root, body)
            out = root / "out"
            suggest_workflow(analysis, target="pi", out=out, task="restore final-report gate")
            js = (out / "workflow.js").read_text(encoding="utf-8")
            self.assertIn('name: "sg_pipeline_contract_repair"', js)
            self.assertIn("check-contract", js)
            self.assertIn("repair-producer", js)
            self.assertIn("verify-artifacts", js)

    def test_claude_target(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root)
            out = root / "out-claude"
            self.assertEqual(
                main(["suggest-workflow", str(analysis), "--target", "claude", "--out", str(out)]),
                0,
            )
            js = (out / "workflow.js").read_text(encoding="utf-8")
            self.assertIn("agent(", js)
            self.assertTrue("phase(" in js or "budget" in js)
            # Content-free: fixture summaries must not leak into the sketch as raw transcript.
            self.assertNotIn("secret-user-utterance", js)

    def test_claude_does_not_embed_transcript_text(self):
        body = dict(FIXTURE_ANALYSIS)
        body["findings"] = [
            {
                "code": "repeated_action",
                "severity": "warning",
                "summary": "user said PLEASE_PASTE_MY_SECRET_PROMPT into the tool",
                "evidence": ["e1"],
                "recommendation": "budget",
            }
        ]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root, body)
            out = root / "out"
            suggest_workflow(analysis, target="claude", out=out)
            js = (out / "workflow.js").read_text(encoding="utf-8")
            self.assertNotIn("PLEASE_PASTE_MY_SECRET_PROMPT", js)

    def test_agentctl_target(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root)
            out = root / "out-agentctl"
            self.assertEqual(
                main(["suggest-workflow", str(analysis), "--target", "agentctl", "--out", str(out)]),
                0,
            )
            self.assertTrue((out / "task.md").is_file())
            self.assertTrue((out / "run.yaml").is_file())
            self.assertTrue((out / "rubric.md").is_file())
            run_yaml = (out / "run.yaml").read_text(encoding="utf-8")
            self.assertIn("repeatedFailureRounds: 2", run_yaml)
            self.assertIn("never auto-runs agentctl", run_yaml)

    def test_severity_spine_dead_end_owns_handoff(self):
        body = {
            "schema_version": 1,
            "session": {"id": "spine", "format": "pi-v3", "source": "x", "metadata": {}},
            "metrics": {"workflow_health": 50, "tool_calls": 1, "events": 4, "branches": 0},
            "findings": [
                {
                    "code": "user_correction",
                    "severity": "warning",
                    "summary": "correction",
                    "evidence": ["u1"],
                    "recommendation": "checklist",
                },
                {
                    "code": "dead_end",
                    "severity": "warning",
                    "summary": "dead end",
                    "evidence": ["a9"],
                    "recommendation": "handoff",
                },
            ],
            "graph": {"nodes": [], "edges": []},
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root, body)
            out = root / "out"
            suggest_workflow(analysis, target="markdown", out=out)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["primary_finding"], "dead_end")
            rationale = (out / "rationale.md").read_text(encoding="utf-8")
            self.assertIn("### Spine: `dead_end`", rationale)
            self.assertIn("### Guard: `user_correction`", rationale)
            workflow = (out / "workflow.md").read_text(encoding="utf-8")
            self.assertIn("Handoff", workflow)
            self.assertIn("PreflightChecklist", workflow)

    def test_no_findings_skips_without_include_healthy(self):
        body = {
            "schema_version": 1,
            "session": {"id": "ok", "format": "pi-v3", "source": "x", "metadata": {}},
            "metrics": {"workflow_health": 100, "tool_calls": 0, "events": 2, "branches": 0},
            "findings": [],
            "graph": {"nodes": [], "edges": []},
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root, body)
            out = root / "out"
            self.assertEqual(
                main(["suggest-workflow", str(analysis), "--target", "markdown", "--out", str(out)]),
                0,
            )
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["skipped"])
            self.assertTrue((out / "SKIPPED.md").is_file())
            self.assertFalse((out / "workflow.md").exists())

    def test_no_findings_include_healthy_emits_linear(self):
        body = {
            "schema_version": 1,
            "session": {"id": "ok", "format": "pi-v3", "source": "x", "metadata": {}},
            "metrics": {"workflow_health": 100, "tool_calls": 0, "events": 2, "branches": 0},
            "findings": [],
            "graph": {"nodes": [], "edges": []},
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root, body)
            out = root / "out"
            self.assertEqual(
                main([
                    "suggest-workflow", str(analysis),
                    "--target", "markdown", "--out", str(out), "--include-healthy",
                ]),
                0,
            )
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["skipped"])
            self.assertTrue(manifest["healthy_template"])
            workflow = (out / "workflow.md").read_text(encoding="utf-8")
            self.assertIn("Start → Do → Verify → Done", workflow)

    def test_does_not_shell_out(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            analysis = self._write_analysis(root)
            out = root / "out"

            def _blocked(*_args, **_kwargs):
                raise AssertionError("suggest-workflow must not spawn subprocesses")

            with patch("subprocess.run", _blocked), patch("subprocess.call", _blocked), patch(
                "subprocess.Popen", _blocked
            ), patch("os.system", _blocked):
                self.assertEqual(
                    main(["suggest-workflow", str(analysis), "--target", "agentctl", "--out", str(out)]),
                    0,
                )
                self.assertEqual(
                    main(["suggest-workflow", str(analysis), "--target", "pi", "--out", str(out / "pi")]),
                    0,
                )

    def test_report_dir_and_jsonl_inputs(self):
        fixture = Path(__file__).parent / "fixtures" / "pi-loop.jsonl"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report"
            self.assertEqual(main(["analyze", str(fixture), "--out", str(report)]), 0)
            out_dir = root / "from-dir"
            self.assertEqual(
                main(["suggest-workflow", str(report), "--target", "markdown", "--out", str(out_dir)]),
                0,
            )
            self.assertIn("repeated_action", json.loads((out_dir / "manifest.json").read_text())["findings_used"])

            out_jsonl = root / "from-jsonl"
            self.assertEqual(
                main(["suggest-workflow", str(fixture), "--target", "claude", "--out", str(out_jsonl)]),
                0,
            )
            self.assertTrue((out_jsonl / "workflow.js").is_file())

    def test_select_and_map_helpers(self):
        selected = select_findings(FIXTURE_ANALYSIS["findings"], max_findings=1)
        self.assertEqual(len(selected), 1)
        # Same severity: spine priority prefers errors (1) over repeated_action (3)? 
        # Actually errors has SPINE_PRIORITY 1, repeated_action 3 — so errors wins for max 1.
        self.assertEqual(selected[0]["code"], "errors")
        plan = map_topology(FIXTURE_ANALYSIS["findings"])
        self.assertEqual(plan["primary_finding"], "errors")
        self.assertIn("repeated_action", plan["findings_used"])

    def test_malformed_analysis_exits_2(self):
        with TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.json"
            bad.write_text('{"no":"findings"}\n', encoding="utf-8")
            self.assertEqual(main(["suggest-workflow", str(bad), "--out", str(Path(directory) / "o")]), 2)


if __name__ == "__main__":
    unittest.main()
