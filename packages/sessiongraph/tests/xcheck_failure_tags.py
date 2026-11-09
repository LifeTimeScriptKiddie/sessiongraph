#!/usr/bin/env python3
"""Cross-check SessionGraph Python tags against a TS classifyTags dump (optional).

Usage:
  node -e '...' > /tmp/ts-tags.json   # or use --write-ts from agentctl fixtures
  uv run --frozen python tests/xcheck_failure_tags.py /tmp/ts-tags.json

If no TS dump is given, this script only verifies Python golden fixtures and exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "fixtures" / "failure-tags"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sessiongraph.failure_tags import classify_agentctl  # noqa: E402


def main(argv: list[str]) -> int:
    mismatches = 0
    for path in sorted(FIX.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        expected = doc.pop("expected_tags")
        got = classify_agentctl(doc)
        if got != expected:
            print(f"PY mismatch {path.name}: got={got} expected={expected}")
            mismatches += 1
        else:
            print(f"PY ok {path.name}: {got}")

    if len(argv) >= 2:
        ts_path = Path(argv[1])
        ts_doc = json.loads(ts_path.read_text(encoding="utf-8"))
        # Expect { "<fixture-name>": ["tag", ...] }
        for name, tags in ts_doc.items():
            py_path = FIX / name
            if not py_path.exists():
                print(f"TS-only fixture missing in Python set: {name}")
                mismatches += 1
                continue
            doc = json.loads(py_path.read_text(encoding="utf-8"))
            doc.pop("expected_tags", None)
            py_tags = classify_agentctl(doc)
            if sorted(tags) != py_tags:
                print(f"TS/PY disagree on {name}: ts={sorted(tags)} py={py_tags}")
                mismatches += 1
            else:
                print(f"TS/PY agree {name}: {py_tags}")

    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
