import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sessiongraph.cli import main
from sessiongraph.reader_health import check

HUMAN = {"origin": {"kind": "human"}, "promptSource": "typed", "entrypoint": "cli", "sessionId": "s", "version": "2.1.288"}


def _records(n=12):
    out = []
    for i in range(n):
        out.append({"type": "user", "uuid": f"u{i}", "timestamp": f"2026-09-2{i % 3}T10:00:00Z",
                    "message": {"role": "user", "content": f"task {i}"}, **HUMAN})
        out.append({"type": "assistant", "uuid": f"a{i}", "timestamp": f"2026-09-2{i % 3}T10:00:01Z", "sessionId": "s",
                    "message": {"id": f"m{i}", "usage": {"output_tokens": 10},
                                "content": [{"type": "tool_use", "id": f"t{i}", "name": "Read", "input": {"file_path": "/x"}}]}})
        out.append({"type": "user", "uuid": f"r{i}", "timestamp": f"2026-09-2{i % 3}T10:00:02Z", "sessionId": "s",
                    "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}})
    return out


def _write(root: Path, records) -> Path:
    path = root / "proj" / "s.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return root


def _renamed(transform):
    return [transform(json.loads(json.dumps(r))) for r in _records()]


def _rename_block(rec):
    for block in rec["message"].get("content") if isinstance(rec["message"].get("content"), list) else []:
        if block["type"] == "tool_use":
            block["type"] = "tool_call"
    return rec


class HealthTests(unittest.TestCase):
    def test_healthy_transcripts_pass_and_reader_matches_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = check(_write(Path(tmp), _records()))
        self.assertEqual((report["verdict"], report["drift"]), ("ok", []))
        self.assertEqual(report["totals"]["tool_use"], 12)
        self.assertEqual(report["rates"]["origin_coverage"], 1.0)

    def test_renamed_fields_are_drift_not_empty_success(self):
        cases = {
            "unknown_block_rate": _rename_block,
            "missing_message_rate": lambda r: {**{k: v for k, v in r.items() if k != "message"}, "msg": r["message"]},
            "conversation_share": lambda r: {**{k: v for k, v in r.items() if k != "type"}, "kind": r["type"]},
            "unpaired_result_rate": lambda r: (r["message"]["content"][0].update(tool_use_id="other")
                                               if r["uuid"].startswith("r") else None) or r,
        }
        for signal, transform in cases.items():
            with self.subTest(signal=signal), tempfile.TemporaryDirectory() as tmp:
                report = check(_write(Path(tmp), _renamed(transform)))
                self.assertEqual(report["verdict"], "drift")
                self.assertIn(signal, report["drift"])

    def test_reader_disagreeing_with_raw_is_drift(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("sessiongraph.reader_health.reader_counts",
                      return_value={"tool_use": 0, "tool_result": 12, "user_text": 12}):
            report = check(_write(Path(tmp), _records()))
        self.assertIn("reader_matches_raw", report["drift"])
        self.assertEqual(report["mismatched"][0]["counts"], {"tool_use": {"raw": 12, "reader": 0}})

    def test_baseline_catches_coverage_drop_and_notes_new_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = check(_write(Path(tmp), _records()))
        stripped = _renamed(lambda r: ({k: v for k, v in r.items() if k not in {"origin", "promptSource"}}
                                       | {"version": "2.2.0"}))
        with tempfile.TemporaryDirectory() as tmp:
            report = check(_write(Path(tmp), stripped), baseline)
        self.assertIn("origin_coverage_vs_baseline", report["drift"])
        self.assertEqual(report["notes"]["new_versions"], ["2.2.0"])


class GuardTests(unittest.TestCase):
    def test_commands_refuse_to_publish_on_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _write(Path(tmp), _renamed(_rename_block))
            out = Path(tmp) / "out"
            self.assertEqual(main(["workflows", "--claude-code", str(root), "--out", str(out)]), 3)
            self.assertFalse(out.exists(), "nothing is written when the reader may be wrong")
            self.assertEqual(main(["verify-outcomes", "--claude-code", str(root)]), 3)
            self.assertEqual(main(["label-loops", "--claude-code", str(root), "--out", str(Path(tmp) / "l.jsonl")]), 3)
            self.assertEqual(main(["workflows", "--claude-code", str(root), "--out", str(out), "--allow-drift"]), 0)
            doc = json.loads((out / "workflows.json").read_text())
        self.assertEqual(doc["reader_health"]["verdict"], "drift")

    def test_reader_health_command_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            healthy = _write(Path(tmp) / "a", _records())
            drifted = _write(Path(tmp) / "b", _renamed(_rename_block))
            self.assertEqual(main(["reader-health", "--claude-code", str(healthy), "--out", str(Path(tmp) / "h.json")]), 0)
            self.assertEqual(main(["reader-health", "--claude-code", str(drifted)]), 1)
            self.assertEqual(main(["reader-health", "--claude-code", str(drifted),
                                   "--baseline", str(Path(tmp) / "h.json")]), 1)


if __name__ == "__main__":
    unittest.main()
