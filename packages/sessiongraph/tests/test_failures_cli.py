"""Acceptance tests for `sessiongraph failures` (S3)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sessiongraph.cli import main


class FailuresCliTests(unittest.TestCase):
    def test_aggregates_provider_aup_vs_usage_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "agentctl"
            out = Path(tmp) / "out"
            jobs = home / "jobs"
            # Legacy mislabeled refusal
            d1 = jobs / "job_legacy"
            d1.mkdir(parents=True)
            (d1 / "result.json").write_text(json.dumps({
                "ask": {
                    "agent": "claude",
                    "model": "claude-opus-5-5",
                    "ok": False,
                    "failureClass": "usage_limit",
                    "evidence": json.dumps([
                        {"type": "system", "subtype": "model_refusal_no_fallback",
                         "api_refusal_category": "cyber"},
                    ]),
                },
            }) + "\n", encoding="utf-8")
            # Real usage limit
            d2 = jobs / "job_limit"
            d2.mkdir(parents=True)
            (d2 / "result.json").write_text(json.dumps({
                "ask": {
                    "agent": "codex",
                    "model": "gpt-6-luna",
                    "ok": False,
                    "failureClass": "usage_limit",
                    "text": "You have hit your usage limit.",
                    "evidence": "",
                },
            }) + "\n", encoding="utf-8")
            code = main(["failures", "--agentctl-home", str(home), "--out", str(out)])
            self.assertEqual(code, 0)
            doc = json.loads((out / "failures.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], "sessiongraph.failures.v1")
            self.assertEqual(doc["totals"]["provider_aup"], 1)
            self.assertEqual(doc["totals"]["usage_limit"], 1)
            self.assertEqual(doc["totals"]["legacy_relabel"], 1)
            self.assertTrue((out / "failures.md").is_file())


if __name__ == "__main__":
    unittest.main()
