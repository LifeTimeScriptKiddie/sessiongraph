import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sessiongraph.graph_metrics import measure_graph
from sessiongraph.visualize import write_interactive_html


def analysis(nodes, edges):
    return {
        "session": {"id": "artifact-lineage"},
        "graph": {"nodes": nodes, "edges": edges},
    }


class GraphMetricsTests(unittest.TestCase):
    def test_reachability_and_artifact_verification_coverage(self):
        value = analysis([
            {"id": "request", "kind": "user_request", "is_error": False},
            {"id": "run", "kind": "agent_run", "is_error": False},
            {"id": "artifact-a", "kind": "artifact", "is_error": False},
            {"id": "artifact-b", "kind": "artifact", "is_error": False},
            {"id": "test", "kind": "test_run", "is_error": False},
            {"id": "response", "kind": "final_response", "is_error": False},
        ], [
            {"from": "request", "to": "run", "relation": "requested"},
            {"from": "run", "to": "artifact-a", "relation": "created"},
            {"from": "run", "to": "artifact-b", "relation": "modified"},
            {"from": "artifact-a", "to": "test", "relation": "verified_by"},
            {"from": "test", "to": "response", "relation": "supports"},
        ])
        result = measure_graph(value)
        metrics = result["metrics"]
        self.assertTrue(metrics["is_directed_acyclic"])
        self.assertEqual(metrics["max_depth"], 4)
        self.assertEqual(metrics["request_output_coverage"], 1.0)
        self.assertEqual(metrics["artifact_verification_coverage"], 0.5)
        self.assertEqual(result["evidence"]["verified_artifacts"], ["artifact-a"])

    def test_cycle_and_missing_parent_are_measured(self):
        result = measure_graph(analysis([
            {"id": "a", "kind": "event"}, {"id": "b", "kind": "event"},
        ], [
            {"from": "a", "to": "b"}, {"from": "b", "to": "a"},
            {"from": "missing", "to": "a"},
        ]))
        self.assertFalse(result["metrics"]["is_directed_acyclic"])
        self.assertEqual(result["metrics"]["cycle_nodes"], 2)
        self.assertEqual(result["metrics"]["implicit_nodes"], 1)
        self.assertIsNone(result["metrics"]["max_depth"])

    def test_iseeagents_request_and_response_kinds_have_coverage(self):
        result = measure_graph(analysis([
            {"id": "payload", "kind": "iseeagents_payload"},
            {"id": "response", "kind": "iseeagents_response"},
        ], [{"from": "payload", "to": "response", "relation": "response_to"}]))
        self.assertEqual(result["metrics"]["request_roots"], 1)
        self.assertEqual(result["metrics"]["outputs"], 1)
        self.assertEqual(result["metrics"]["request_output_coverage"], 1.0)

    def test_iseeagents_user_load_is_a_request_root(self):
        result = measure_graph(analysis([
            {"id": "user", "kind": "iseeagents_load", "role": "user_input"},
            {"id": "response", "kind": "iseeagents_response", "role": "model_output"},
        ], [{"from": "user", "to": "response", "relation": "response_to"}]))
        self.assertEqual(result["metrics"]["request_roots"], 1)
        self.assertEqual(result["metrics"]["request_output_coverage"], 1.0)

    def test_visualization_is_self_contained_and_content_free(self):
        value = analysis([
            {"id": "request</script><script>bad()", "kind": "user_request", "role": "user",
             "name": "unsafe</script><script>bad()"},
            {"id": "response", "kind": "final_response", "role": "assistant", "name": None},
        ], [{"from": "request</script><script>bad()", "to": "response", "relation": "supports"}])
        value["private_transcript"] = "DO-NOT-EMBED"
        with TemporaryDirectory() as directory:
            output = write_interactive_html(value, Path(directory) / "graph.html")
            body = output.read_text(encoding="utf-8")
            self.assertIn("supports", body)
            self.assertIn("user_request", body)
            self.assertNotIn("DO-NOT-EMBED", body)
            self.assertNotIn("unsafe</script><script>bad()", body)
            self.assertGreater(len(body), 100_000)


if __name__ == "__main__":
    unittest.main()
