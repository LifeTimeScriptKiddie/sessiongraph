"""Acceptance tests for SessionGraph failure-tag classifier (S1)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from sessiongraph.failure_tags import classify_agentctl

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "failure-tags"


class FailureTagsTests(unittest.TestCase):
    def test_golden_fixtures(self) -> None:
        files = sorted(FIX.glob("*.json"))
        self.assertTrue(files, f"missing fixtures under {FIX}")
        for path in files:
            with self.subTest(path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                expected = doc.pop("expected_tags")
                got = classify_agentctl(doc)
                self.assertEqual(got, expected)

    def test_schema_enum_coverage(self) -> None:
        schema = json.loads(
            (Path(__file__).resolve().parents[3] / "contracts" / "sessiongraph-failure-tags.v1.schema.json")
            .read_text(encoding="utf-8")
        )
        enum = set(schema["properties"]["tags"]["items"]["enum"])
        # Every golden tag must be in the schema enum.
        for path in FIX.glob("*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for tag in doc["expected_tags"]:
                self.assertIn(tag, enum)


if __name__ == "__main__":
    unittest.main()
