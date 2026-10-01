import unittest
from pathlib import Path

from sessiongraph.analyze import BASE_CHECKS, analyze, compare
from sessiongraph.model import Event, Session
from sessiongraph.parsers import load_session
from sessiongraph.scorecard import evaluate_scorecard

AGENTCTL_FIXTURE = Path(__file__).parent / "fixtures" / "agentctl-loop.jsonl"


def _session(failing_tools: list[str], end_ok: bool = True) -> Session:
    """Each name is one tool call whose result fails; an optional final success keeps it off dead_end."""
    events = [Event("u", None, "message", role="user")]
    for index, name in enumerate(failing_tools):
        events.append(Event(f"c{index}", events[-1].id, "tool_call", name=name, signature=name))
        events.append(Event(f"r{index}", f"c{index}", "tool_result", is_error=True))
    if end_ok:
        events.append(Event("done", events[-1].id, "message", role="assistant"))
    return Session("s", "s.jsonl", "generic-jsonl", events)


def _checks(result):
    return {check["code"]: check for check in result["checks"]}


class CheckTests(unittest.TestCase):
    def test_every_base_check_is_answered_even_when_it_does_not_fire(self):
        checks = _checks(analyze(_session([])))
        self.assertEqual(set(BASE_CHECKS), set(checks))
        self.assertEqual(checks["errors"]["value"], 0)
        self.assertIs(checks["dead_end"]["value"], False)
        self.assertFalse(any(check["fired"] for check in checks.values()))

    def test_values_are_measured_and_evidence_links_events_to_the_check(self):
        checks = _checks(analyze(_session(["grep", "grep", "grep"], end_ok=False)))
        self.assertEqual(checks["repeated_action"]["value"], 1)
        self.assertEqual(checks["errors"]["value"], 3)
        self.assertIs(checks["dead_end"]["value"], True)
        self.assertEqual(checks["repeated_action"]["evidence"], ["c0", "c1", "c2"])
        self.assertEqual(checks["repeated_action"]["basis"], "heuristic")
        self.assertEqual(checks["dead_end"]["basis"], "definition")
        self.assertEqual(checks["dead_end"]["id"], "check:dead_end")

    def test_agentctl_checks_include_measured_bottleneck_share(self):
        checks = _checks(analyze(load_session(AGENTCTL_FIXTURE)))
        self.assertTrue({"loop_incomplete", "loop_telemetry_gap", "agent_timeout", "loop_bottleneck"} <= set(checks))
        self.assertIsInstance(checks["loop_bottleneck"]["value"], float)
        self.assertGreaterEqual(checks["loop_bottleneck"]["value"], 0.75)

    def test_compare_reports_check_value_changes(self):
        before = analyze(_session(["a", "b"], end_ok=True))
        after = analyze(_session(["a", "b", "c", "d"], end_ok=True))
        delta = compare(before, after)["check_delta"]
        self.assertEqual(delta["errors"], 2)
        self.assertEqual(delta["dead_end"], 0)


class ScorecardCheckTests(unittest.TestCase):
    def test_worse_value_fails_even_when_finding_counts_and_health_tie(self):
        before = analyze(_session(["a"]))
        after = analyze(_session(["a", "b", "c"]))
        self.assertEqual(len(before["findings"]), len(after["findings"]))
        before["metrics"]["workflow_health"] = after["metrics"]["workflow_health"] - 1
        card = evaluate_scorecard(before, after)
        self.assertFalse(card["ok"])
        self.assertEqual(card["failed_gates"], ["no_worse_checks"])
        row = next(r for r in card["gates"] if r["id"] == "no_worse_checks")
        self.assertEqual(row["observed"], ["errors"])

    def test_one_sided_checks_fail_closed_and_legacy_pairs_skip_the_gate(self):
        before, after = analyze(_session(["a"])), analyze(_session([]))
        legacy = dict(before)
        legacy.pop("checks")
        card = evaluate_scorecard(legacy, after)
        self.assertIn("no_worse_checks", card["failed_gates"])
        legacy_after = dict(after)
        legacy_after.pop("checks")
        ids = {row["id"] for row in evaluate_scorecard(legacy, legacy_after)["gates"]}
        self.assertNotIn("no_worse_checks", ids)


if __name__ == "__main__":
    unittest.main()
