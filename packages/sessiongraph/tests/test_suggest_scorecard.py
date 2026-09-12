"""Fixture matrix + compare scorecard for suggest-map-v1 accuracy."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sessiongraph.cli import main
from sessiongraph.scorecard import SCORECARD_VERSION, evaluate_scorecard
from sessiongraph.suggest import MAPPING_VERSION, topology_digest, topology_snapshot


MATRIX_ROOT = Path(__file__).parent / "fixtures" / "suggest-matrix"


def _load_cases() -> list[dict]:
    body = json.loads((MATRIX_ROOT / "cases.json").read_text(encoding="utf-8"))
    assert body["mapping_version"] == MAPPING_VERSION
    return list(body["cases"])


class SuggestMatrixTests(unittest.TestCase):
    def test_matrix_matches_goldens(self):
        for case in _load_cases():
            with self.subTest(case=case["id"]):
                analysis = json.loads((MATRIX_ROOT / case["analysis"]).read_text(encoding="utf-8"))
                expected = json.loads((MATRIX_ROOT / case["expected"]).read_text(encoding="utf-8"))
                actual = topology_snapshot(analysis, include_healthy=False)
                self.assertEqual(actual, expected)
                self.assertEqual(topology_digest(actual), topology_digest(expected))

    def test_determinism_same_findings_same_digest(self):
        analysis = json.loads(
            (MATRIX_ROOT / "multi_fault_contract_dead_end_retry" / "analysis.json").read_text(
                encoding="utf-8"
            )
        )
        a = topology_snapshot(analysis)
        b = topology_snapshot(analysis)
        self.assertEqual(a, b)
        self.assertEqual(topology_digest(a), topology_digest(b))

    def test_healthy_include_healthy_golden(self):
        analysis = json.loads(
            (MATRIX_ROOT / "healthy_empty" / "analysis.json").read_text(encoding="utf-8")
        )
        expected = json.loads(
            (MATRIX_ROOT / "healthy_empty" / "expected_topology_include_healthy.json").read_text(
                encoding="utf-8"
            )
        )
        actual = topology_snapshot(analysis, include_healthy=True)
        self.assertEqual(actual, expected)
        self.assertEqual(actual["pi_meta_name"], "sg_healthy_linear")

    def test_pi_target_dry_shape_on_matrix(self):
        analysis_path = MATRIX_ROOT / "errors_plus_repeated" / "analysis.json"
        with TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            self.assertEqual(
                main(["suggest-workflow", str(analysis_path), "--target", "pi", "--out", str(out)]),
                0,
            )
            js = (out / "workflow.js").read_text(encoding="utf-8")
            self.assertTrue(js.lstrip().startswith("export const meta"))
            self.assertIn("phase(", js)
            self.assertIn("agent(", js)
            expected = json.loads(
                (MATRIX_ROOT / "errors_plus_repeated" / "expected_topology.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn(expected["pi_meta_name"], js)

    def test_multi_fault_contract_spine_beats_retry_guard(self):
        """pipeline_contract primary keeps contract phases; RetryBudget before VerifyArtifacts."""
        analysis = json.loads(
            (MATRIX_ROOT / "multi_fault_contract_dead_end_retry" / "analysis.json").read_text(
                encoding="utf-8"
            )
        )
        snap = topology_snapshot(analysis)
        self.assertEqual(snap["primary_finding"], "pipeline_contract")
        self.assertEqual(
            snap["pi_phases"],
            [
                "check-contract",
                "repair-producer",
                "verify-artifacts",
                "bounded-retry",
                "retry-with-new-hypothesis",
                "handoff",
            ],
        )
        self.assertEqual(
            snap["markdown_graph"],
            "Start → CheckContract → RepairProducer → RetryBudget(2) → VerifyArtifacts → Handoff → Done",
        )
        self.assertNotIn("Done → RetryBudget", snap["markdown_graph"])
        with TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            analysis_path = MATRIX_ROOT / "multi_fault_contract_dead_end_retry" / "analysis.json"
            self.assertEqual(
                main(["suggest-workflow", str(analysis_path), "--target", "pi", "--out", str(out)]),
                0,
            )
            js = (out / "workflow.js").read_text(encoding="utf-8")
            # Contract body must appear before retry-guard phases.
            check_idx = js.index("check-contract")
            retry_idx = js.index("bounded-retry")
            self.assertLess(check_idx, retry_idx)
            self.assertIn("repair-producer", js)
            self.assertIn("verify-artifacts", js)


class ScorecardTests(unittest.TestCase):
    def _analysis(self, *, health: int, findings: list[dict], session_id: str = "s") -> dict:
        return {
            "schema_version": 1,
            "session": {"id": session_id, "format": "pi-v3", "source": "x", "metadata": {}},
            "metrics": {
                "workflow_health": health,
                "tool_calls": 2,
                "events": 4,
                "branches": 0,
            },
            "findings": findings,
            "graph": {"nodes": [], "edges": []},
        }

    def test_pass_health_up_findings_down(self):
        before = self._analysis(
            health=46,
            findings=[
                {"code": "repeated_action", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""},
                {"code": "errors", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""},
            ],
            session_id="baseline",
        )
        after = self._analysis(
            health=88,
            findings=[],
            session_id="followed",
        )
        card = evaluate_scorecard(before, after)
        self.assertTrue(card["ok"])
        self.assertEqual(card["scorecard_version"], SCORECARD_VERSION)
        self.assertEqual(card["compare"]["delta"]["workflow_health"], 42)
        self.assertEqual(card["compare"]["finding_delta"], -2)

    def test_fail_health_regression(self):
        before = self._analysis(health=80, findings=[], session_id="a")
        after = self._analysis(
            health=70,
            findings=[{"code": "errors", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""}],
            session_id="b",
        )
        card = evaluate_scorecard(before, after)
        self.assertFalse(card["ok"])
        ids = {row["id"]: row["ok"] for row in card["gates"]}
        self.assertFalse(ids["workflow_health_delta"])
        self.assertFalse(ids["finding_delta"])

    def test_fail_new_dangling_edges(self):
        before = self._analysis(health=50, findings=[], session_id="a")
        after = self._analysis(
            health=90,
            findings=[
                {"code": "dangling_edges", "severity": "info", "summary": "x", "evidence": [], "recommendation": ""}
            ],
            session_id="b",
        )
        card = evaluate_scorecard(before, after)
        self.assertFalse(card["ok"])
        dangling = next(row for row in card["gates"] if row["id"] == "no_new_dangling_edges")
        self.assertFalse(dangling["ok"])

    def test_fail_new_critical(self):
        before = self._analysis(
            health=40,
            findings=[
                {"code": "repeated_action", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""}
            ],
            session_id="a",
        )
        after = self._analysis(
            health=90,
            findings=[
                {"code": "pipeline_contract", "severity": "critical", "summary": "x", "evidence": [], "recommendation": ""}
            ],
            session_id="b",
        )
        card = evaluate_scorecard(before, after)
        self.assertFalse(card["ok"])
        critical = next(row for row in card["gates"] if row["id"] == "no_new_critical_findings")
        self.assertFalse(critical["ok"])

    def test_cli_scorecard_exit_codes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            before = self._analysis(health=46, findings=[
                {"code": "errors", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""}
            ], session_id="before")
            after_pass = self._analysis(health=88, findings=[], session_id="after")
            after_fail = self._analysis(health=40, findings=[
                {"code": "errors", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""},
                {"code": "dead_end", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""},
            ], session_id="worse")
            bp = root / "before.json"
            ap = root / "after.json"
            fp = root / "fail.json"
            bp.write_text(json.dumps(before) + "\n", encoding="utf-8")
            ap.write_text(json.dumps(after_pass) + "\n", encoding="utf-8")
            fp.write_text(json.dumps(after_fail) + "\n", encoding="utf-8")
            out = root / "scorecard.json"
            self.assertEqual(main(["scorecard", str(bp), str(ap), "--out", str(out)]), 0)
            body = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(body["ok"])
            self.assertEqual(main(["scorecard", str(bp), str(fp)]), 1)

    def test_live_closed_loop_numbers(self):
        """Regression against the documented 46→88 closed-loop proof (synthetic metrics)."""
        before = self._analysis(
            health=46,
            findings=[
                {"code": "repeated_action", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""},
                {"code": "errors", "severity": "warning", "summary": "x", "evidence": [], "recommendation": ""},
            ],
            session_id="fixture-pi-loop",
        )
        after = self._analysis(health=88, findings=[], session_id="live-closed-loop-followed-graph")
        card = evaluate_scorecard(before, after)
        self.assertTrue(card["ok"])
        self.assertEqual(card["compare"]["delta"]["workflow_health"], 42)
        self.assertEqual(card["compare"]["finding_delta"], -2)


if __name__ == "__main__":
    unittest.main()
