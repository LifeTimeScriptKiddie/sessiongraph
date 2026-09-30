import json
import tempfile
import unittest
from pathlib import Path

from sessiongraph.cli import main
from sessiongraph.verify import SCHEMA, author_of, label_sheet, read_turns, verify

SECRET = "SECRET-PROMPT-TEXT"
HUMAN = {"origin": {"kind": "human"}, "promptSource": "typed", "entrypoint": "cli"}


def _user(uid, text, **extra):
    return {"type": "user", "uuid": uid, "timestamp": "2026-09-20T10:00:00Z",
            "message": {"role": "user", "content": text}, **extra}


def _tool(tid, name, command=""):
    return {"type": "assistant", "timestamp": "2026-09-20T10:00:01Z", "message": {
        "id": f"m_{tid}", "content": [{"type": "tool_use", "id": tid, "name": name, "input": {"command": command}}]}}


def _write(path: Path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


class AuthorTests(unittest.TestCase):
    def test_author_comes_from_recorded_fields(self):
        self.assertEqual(author_of(HUMAN, "x")[0], "human")
        self.assertEqual(author_of({"entrypoint": "sdk-cli", "promptSource": "sdk"}, "no, read x")[0], "agent")
        self.assertEqual(author_of({"origin": {"kind": "peer"}}, "x")[0], "agent")
        self.assertEqual(author_of({"origin": {"kind": "task-notification"}}, "x")[0], "system")
        self.assertEqual(author_of({"isMeta": True, **HUMAN}, "x")[0], "system")
        self.assertEqual(author_of({}, "This session is being continued from a previous conversation")[0], "system")
        self.assertEqual(author_of({}, "hello")[0], "unknown")


class SignalTests(unittest.TestCase):
    def test_interrupt_rejection_and_revert_are_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "s.jsonl", [
                _user("u1", "build it", **HUMAN),
                _tool("t1", "Edit"),
                {"type": "user", "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}},
                _user("u2", "go back to chrome", **HUMAN),
                _tool("t2", "Bash", "git restore src/a.ts"),
                _user("u3", "ok now add tests", **HUMAN),
                _tool("t3", "Edit"),
                {"type": "user", "toolDenialKind": "user-rejected", "message": {"content": [{"type": "tool_result"}]}},
                _user("u4", "use the other file", **HUMAN),
                {"type": "user", "toolDenialKind": "automode-blocked", "message": {"content": [{"type": "tool_result"}]}},
                _user("u5", "continue", **HUMAN),
            ])
            turns = {t.id: t for t in read_turns(path)}
        self.assertTrue(turns["u2"].stopped_before)
        self.assertTrue(turns["u2"].reverted_after)
        self.assertFalse(turns["u3"].stopped_before)
        self.assertTrue(turns["u4"].stopped_before)
        self.assertFalse(turns["u5"].stopped_before, "a classifier denial is not a human stopping the agent")
        self.assertFalse(turns["u1"].reverted_after)

    def test_revert_outside_window_does_not_count(self):
        records = [_user("u1", "do it", **HUMAN)] + [_tool(f"t{i}", "Read") for i in range(5)]
        records.append(_tool("late", "Bash", "git reset --hard"))
        with tempfile.TemporaryDirectory() as tmp:
            (turn,) = read_turns(_write(Path(tmp) / "s.jsonl", records))
        self.assertFalse(turn.reverted_after)


class SheetTests(unittest.TestCase):
    def test_sheet_is_content_free_and_keyword_on_agent_turn_is_flagged_only_by_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "s.jsonl", [
                _user("h1", f"no, that's wrong {SECRET}", **HUMAN),
                _user("a1", f"Read x. no, not y {SECRET}", entrypoint="sdk-cli", promptSource="sdk"),
                _user("h2", f"add a README {SECRET}", **HUMAN),
            ])
            self.assertEqual(main(["label-corrections", "--claude-code", str(root), "--out", str(root / "sheet.jsonl")]), 0)
            body = (root / "sheet.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(SECRET, body)
        rows = [json.loads(line) for line in body.splitlines()]
        self.assertEqual(rows[0]["schema"], SCHEMA)
        by_id = {r["turn_id"]: r for r in rows[1:]}
        self.assertEqual(by_id["a1"]["flags"], {"keyword_any_author": True, "keyword_human": False, "behavior": False})
        self.assertTrue(by_id["h1"]["flags"]["keyword_human"])
        self.assertEqual(by_id["h2"]["stratum"], "sample")

    def test_label_refuses_a_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "sheet.jsonl"
            sheet.write_text(json.dumps({"schema": SCHEMA, "kind": "header"}) + "\n", encoding="utf-8")
            self.assertEqual(main(["label", str(sheet)]), 2)


def _row(flags, label, stratum="flagged", by="human"):
    return {"flags": flags, "label": label, "labeled_by": by, "stratum": stratum}


class VerifyTests(unittest.TestCase):
    def _sheet(self, extra=()):
        header = {"schema": SCHEMA, "kind": "header", "unflagged_human": 100, "sample_size": 10,
                  "authors": {}, "detectors": ["good", "noisy"]}
        rows = [header]
        rows += [_row({"good": True, "noisy": True}, True) for _ in range(9)]
        rows += [_row({"good": True, "noisy": True}, False)]
        rows += [_row({"good": False, "noisy": True}, False) for _ in range(20)]
        rows += [_row({"good": False, "noisy": True}, True)]
        rows += [_row({"good": False, "noisy": False}, False, "sample") for _ in range(10)]
        return rows + list(extra)

    def test_precision_and_recall(self):
        report = verify(self._sheet())
        good, noisy = report["detectors"]["good"], report["detectors"]["noisy"]
        self.assertEqual((good["precision"], good["missed_in_flagged"], good["recall_estimated"]), (0.9, 1, 0.9))
        self.assertEqual(good["verdict"], "verified")
        self.assertEqual(noisy["precision"], round(10 / 31, 3))
        self.assertEqual(noisy["verdict"], "unverified")

    def test_misses_in_the_sample_scale_to_the_unflagged_population(self):
        rows = self._sheet()
        rows[-1]["label"] = True  # 1 of 10 sampled is a correction: about 10 of 100 unflagged are missed
        good = verify(rows)["detectors"]["good"]
        self.assertEqual(good["missed_estimated_unflagged"], 10.0)
        self.assertEqual(good["recall_estimated"], 0.45)
        self.assertEqual(good["verdict"], "unverified")

    def test_agent_labels_never_count(self):
        report = verify(self._sheet([_row({"good": True, "noisy": True}, False, by="agent")] * 5))
        self.assertEqual(report["ignored_non_human_labels"], 5)
        self.assertEqual(report["detectors"]["good"]["precision"], 0.9)

    def test_no_sample_labels_means_insufficient(self):
        rows = [r for r in self._sheet() if r.get("stratum") != "sample"]
        self.assertEqual(verify(rows)["detectors"]["good"]["verdict"], "insufficient_labels")

    def test_require_sets_the_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "sheet.jsonl"
            sheet.write_text("".join(json.dumps(r) + "\n" for r in self._sheet()), encoding="utf-8")
            self.assertEqual(main(["verify-detectors", str(sheet), "--require", "good"]), 0)
            self.assertEqual(main(["verify-detectors", str(sheet), "--require", "good", "noisy"]), 1)
            self.assertEqual(main(["verify-detectors", str(sheet), "--require", "missing"]), 2)


if __name__ == "__main__":
    unittest.main()
