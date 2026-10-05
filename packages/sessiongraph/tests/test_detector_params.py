"""Detector defaults and published labeled-corpus summary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from sessiongraph.analyze import _repeated
from sessiongraph.detector_params import load_detector_params, repeated_action_params, verify_thresholds
from sessiongraph.model import Event
from sessiongraph.verify import REVERT_WINDOW, THRESHOLDS


FIXTURES = Path(__file__).parent / "fixtures"


class DetectorParamsTests(unittest.TestCase):
    def test_params_file_matches_runtime_defaults(self):
        params = load_detector_params()
        minimum, window = repeated_action_params()
        self.assertEqual((minimum, window), (3, 8))
        self.assertEqual(params["repeated_action"]["minimum"], minimum)
        self.assertEqual(params["repeated_action"]["window"], window)
        self.assertEqual(THRESHOLDS, verify_thresholds())
        self.assertEqual(REVERT_WINDOW, params["revert_window"])

    def test_repeated_uses_checked_in_defaults(self):
        events = [
            Event("c1", "p", "tool_call", signature="bash:pytest"),
            Event("r1", "c1", "tool_result", is_error=True),
            Event("c2", "p", "tool_call", signature="bash:pytest"),
            Event("r2", "c2", "tool_result", is_error=True),
            Event("c3", "p", "tool_call", signature="bash:pytest"),
            Event("r3", "c3", "tool_result", is_error=True),
        ]
        self.assertEqual(len(_repeated(events)), 1)

    def test_labeled_summary_fixture_matches_verify_doc(self):
        summary = json.loads((FIXTURES / "verify-labeled-summary.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["human_typed_turns"], 320)
        self.assertEqual(summary["detectors"]["behavior"]["verdict"], "unverified")
        params = load_detector_params()
        self.assertEqual(params["labeled_corpus_summary"]["human_typed_turns"], 320)

    def test_sample_label_sheet_loads(self):
        rows = [
            json.loads(line)
            for line in (FIXTURES / "verify-labeled-sample.v1.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(rows[0]["kind"], "header")
        human = [r for r in rows[1:] if r.get("labeled_by") == "human"]
        self.assertGreaterEqual(len(human), 3)


if __name__ == "__main__":
    unittest.main()
