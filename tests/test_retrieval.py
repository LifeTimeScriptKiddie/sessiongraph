import json
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from sessiongraph.analyze import analyze, compare
from sessiongraph.cli import main
from sessiongraph.model import Event
from sessiongraph.retrieval import load_retrieval


class RetrievalTests(unittest.TestCase):
    def payload(self, success=True):
        # Field names/verdicts match standalone_fetch and engine/fetch_chain.py.
        return {"engine": {
            "ok": success, "content": "PRIVATE_PAGE", "final_url": "PRIVATE_URL",
            "must_invoke_playwright_mcp": not success,
            "trace": [
                {"phase": "probe", "executor": "curl_cffi", "verdict": "blocked",
                 "elapsed_s": 2, "url": "PRIVATE_URL", "error": "PRIVATE_ERROR"},
                {"phase": "grid", "executor": "curl_cffi", "verdict": "strong_ok" if success else "blocked",
                 "elapsed_s": 1, "url": "PRIVATE_URL"},
            ],
        }, "harness": {"queue_status": "done" if success else "blocked"}}

    def test_recovered_attempt_metrics_and_private_export(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fetch.json"
            path.write_text(json.dumps(self.payload(), indent=2))
            output = Path(directory) / "report"
            self.assertEqual(main(["analyze-retrieval", str(path), "--out", str(output)]), 0)
            result = json.loads((output / "analysis.json").read_text())
            self.assertEqual(result["metrics"]["retrieval_attempts"], 2)
            self.assertEqual(result["metrics"]["retrieval_unsuccessful_attempts"], 1)
            self.assertEqual(result["metrics"]["retrieval_elapsed_s"], 3)
            self.assertFalse(result["findings"])
            ids = {node["id"] for node in result["graph"]["nodes"]}
            self.assertTrue(all(e["from"] in ids and e["to"] in ids for e in result["graph"]["edges"]))
            for artifact in output.iterdir():
                self.assertNotIn("PRIVATE_", artifact.read_text())

    def test_comparison_measures_attempt_reduction_without_success_loss(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fetch.json"
            baseline = self.payload()
            path.write_text(json.dumps(baseline))
            before = analyze(load_retrieval(path))
            baseline["engine"]["trace"].pop(0)
            path.write_text(json.dumps(baseline))
            after = analyze(load_retrieval(path))
            delta = compare(before, after)["delta"]
            self.assertEqual(delta["retrieval_attempts"], -1)
            self.assertEqual(delta["retrieval_elapsed_s"], -2)
            self.assertEqual(delta["retrieval_success"], 0)

    def test_deferred_escalation_is_not_success(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fetch.json"
            path.write_text(json.dumps(self.payload(False)))
            result = analyze(load_retrieval(path))
            self.assertEqual(result["metrics"]["retrieval_success"], 0)
            self.assertIn("escalation_deferred", {f["code"] for f in result["findings"]})

    def test_invalid_duration_and_schema_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fetch.json"
            for duration in (float("nan"), float("inf"), -1, True, "slow", 10**400):
                payload = self.payload()
                payload["engine"]["trace"][0]["elapsed_s"] = duration
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    load_retrieval(path)
            path.write_text('[]')
            with self.assertRaises(ValueError):
                load_retrieval(path)

    def test_optimized_export_matches_original_and_is_detached(self):
        event = Event("x", None, "message", text="hello", metadata={"nested": [1]})
        for include in (False, True):
            expected = asdict(event)
            if not include:
                expected.pop("text")
            exported = event.public(include)
            self.assertEqual(exported, expected)
            exported["metadata"]["nested"].append(2)
            self.assertEqual(event.metadata["nested"], [1])


if __name__ == "__main__":
    unittest.main()
