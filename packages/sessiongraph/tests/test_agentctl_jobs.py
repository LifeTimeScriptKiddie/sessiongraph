"""Acceptance tests for the agentctl job-store reader (S2 privacy allow-list)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sessiongraph.agentctl_jobs import classify_jobs, iter_jobs, project_record
from sessiongraph.cli import main
from sessiongraph.failure_tags import classify_agentctl
from sessiongraph.reader_health import check_agentctl


SECRET = "SUPER_SECRET_STDOUT_TOKEN_DO_NOT_LEAK_9f3a"


class AgentctlJobsPrivacyTests(unittest.TestCase):
    def test_stdout_secret_never_in_projection(self) -> None:
        raw = {
            "id": "job_secret",
            "kind": "delegate",
            "stdout": SECRET,
            "normalizedText": SECRET,
            "ask": {
                "agent": "claude",
                "model": "claude-opus-4-8",
                "ok": False,
                "failureClass": "provider_refusal",
                "evidence": json.dumps([{"subtype": "model_refusal_no_fallback", "api_refusal_category": "cyber"}]),
                "text": "safe summary without secret",
            },
        }
        projected = project_record(raw)
        blob = json.dumps(projected)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("stdout", projected)
        self.assertNotIn("normalizedText", projected)
        self.assertNotIn("evidence", projected.get("ask", {}))
        self.assertEqual(projected["ask"]["refusal"]["category"], "cyber")

    def test_unknown_failure_class_reader_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            job = home / "jobs" / "job_unknown"
            job.mkdir(parents=True)
            (job / "result.json").write_text(json.dumps({
                "ask": {"agent": "claude", "model": "x", "ok": False, "failureClass": "weird_new_class"},
            }) + "\n", encoding="utf-8")
            (job / "job.json").write_text(json.dumps({"id": "job_unknown", "kind": "delegate"}) + "\n", encoding="utf-8")
            # Plant a deny-listed file that must never be opened/retained.
            (job / "input.json").write_text(json.dumps({"task": SECRET}) + "\n", encoding="utf-8")
            health = check_agentctl(home)
            self.assertEqual(health["verdict"], "drift")
            self.assertIn("unknown_failure_class", health["drift"])
            records = list(iter_jobs(home))
            self.assertEqual(len(records), 1)
            self.assertNotIn(SECRET, json.dumps(records))

    def test_legacy_usage_limit_relabel(self) -> None:
        fix = Path(__file__).resolve().parents[3] / "fixtures" / "failure-tags" / "legacy-usage-limit-with-refusal.json"
        doc = json.loads(fix.read_text(encoding="utf-8"))
        expected = doc.pop("expected_tags")
        tags = classify_agentctl(doc)
        self.assertEqual(tags, expected)
        self.assertIn("provider_aup", tags)
        self.assertIn("legacy_relabel", tags)
        self.assertNotIn("usage_limit", tags)

    def test_failures_cli_exit_3_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "agentctl"
            out = Path(tmp) / "out"
            job = home / "jobs" / "job_unknown"
            job.mkdir(parents=True)
            (job / "result.json").write_text(json.dumps({
                "ask": {"agent": "claude", "model": "x", "ok": False, "failureClass": "not_a_real_class"},
            }) + "\n", encoding="utf-8")
            code = main(["failures", "--agentctl-home", str(home), "--out", str(out)])
            self.assertEqual(code, 3)
            self.assertTrue((out / "failures.json").is_file())


if __name__ == "__main__":
    unittest.main()
