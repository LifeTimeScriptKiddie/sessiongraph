import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sessiongraph.analyze import analyze
from sessiongraph.cli import main
from sessiongraph.memory_plane import SCHEMA, load_memory_plane


class MemoryPlaneTests(unittest.TestCase):
    def payload(self, **overrides):
        base = {
            "schema": SCHEMA,
            "exported_at": "2026-09-22T05:00:00Z",
            "period": {"start": "2026-09-21T05:00:00Z", "end": "2026-09-22T05:00:00Z"},
            "backend": "sqlite",
            "audit": {
                "event_count": 12,
                "routes": {"/v1/turn": 10, "/v1/context": 2},
                "turn_total": 10,
                "turn_abstain": 5,
                "context_total": 2,
                "write_total": 0,
                "accept_total": 0,
                "unique_users": 3,
                "workspaces_active": ["team-sec"],
            },
            "store": {
                "workspaces": ["team-sec"],
                "by_workspace": {"team-sec": {"proposed": 4, "accepted": 2, "forgotten": 0}},
                "proposed_pending_total": 4,
                "accepted_total": 2,
                "forgotten_total": 0,
                "checkpoints": 1,
            },
        }
        base.update(overrides)
        return base

    def analyze_payload(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "memory-plane.json"
            path.write_text(json.dumps(payload))
            return analyze(load_memory_plane(path))

    def test_high_abstain_and_review_backlog_surface(self):
        result = self.analyze_payload(self.payload())
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("high_abstain_rate", codes)
        self.assertEqual(result["metrics"]["turn_abstain_rate"], 0.5)

    def test_empty_catalog_is_critical(self):
        payload = self.payload()
        payload["audit"]["turn_total"] = 25
        payload["audit"]["routes"]["/v1/turn"] = 25
        payload["store"]["accepted_total"] = 0
        payload["store"]["by_workspace"]["team-sec"]["accepted"] = 0
        codes = {item["code"] for item in self.analyze_payload(payload)["findings"]}
        self.assertIn("empty_memory_catalog", codes)

    def test_cli_writes_report_with_architecture_section(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            out = Path(directory) / "out"
            path.write_text(json.dumps(self.payload()))
            self.assertEqual(main(["analyze-memory-plane", str(path), "--out", str(out)]), 0)
            report = (out / "report.md").read_text()
            self.assertIn("Architecture recommendations", report)
            self.assertIn("memory-plane-v1", (out / "analysis.json").read_text())

    def test_wrong_schema_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({"schema": "other"}))
            with self.assertRaises(ValueError):
                load_memory_plane(path)


if __name__ == "__main__":
    unittest.main()
