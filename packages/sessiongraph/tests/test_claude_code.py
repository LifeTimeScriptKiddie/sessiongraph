import json
import tempfile
import unittest
from pathlib import Path

from sessiongraph.analyze import analyze
from sessiongraph.claude_code import read_transcript
from sessiongraph.cli import main
from sessiongraph.parsers import load_session
from sessiongraph.verify import read_requests, read_turns
from sessiongraph.workflows import mine, read_claude_code

SECRET = "SECRET-PROMPT-TEXT"
HUMAN = {"origin": {"kind": "human"}, "promptSource": "typed", "entrypoint": "cli", "sessionId": "s"}


def _rec(kind, uid, content, ts="2026-09-20T10:00:00Z", **extra):
    role = "user" if kind == "user" else "assistant"
    return {"type": kind, "uuid": uid, "sessionId": "s", "timestamp": ts,
            "message": {"role": role, "content": content, **extra.pop("message", {})}, **extra}


def _call(uid, tid, name, inp, msg="m1", tokens=50):
    return _rec("assistant", uid, [{"type": "tool_use", "id": tid, "name": name, "input": inp}],
                message={"id": msg, "model": "claude-opus-5-5", "usage": {"output_tokens": tokens}})


def _result(uid, tid, error=False, **extra):
    return _rec("user", uid, [{"type": "tool_result", "tool_use_id": tid, "is_error": error,
                               "content": f"{SECRET} out"}], **extra)


def _write(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _transcript(root: Path) -> Path:
    main_path = _write(root / "proj" / "s.jsonl", [
        _rec("user", "u1", f"fix the build {SECRET}", **HUMAN),
        _call("a1", "t1", "Bash", {"command": "npm test"}, msg="m1", tokens=40),
        _result("r1", "t1", error=True),
        _call("a2", "t2", "Bash", {"command": "npm test"}, msg="m1", tokens=90),
        _result("r2", "t2"),
        _rec("user", "meta", "skill text", isMeta=True, sessionId="s"),
        _call("a3", "t3", "Agent", {"prompt": "look"}, msg="m2", tokens=10),
        _result("r3", "t3", toolUseResult={"agentId": "abc", "status": "completed"}),
        _rec("user", "u2", [{"type": "text", "text": "[Request interrupted by user]"}], sessionId="s"),
        _rec("user", "u3", "now add docs", **HUMAN),
        _call("a4", "t4", "Edit", {"file_path": "/x/a.md"}, msg="m3", tokens=5),
        _result("r4", "t4"),
    ])
    _write(root / "proj" / "s" / "subagents" / "agent-abc.jsonl", [
        _rec("user", "su1", "look around", isSidechain=True, sessionId="s"),
        _call("sa1", "st1", "Read", {"file_path": "/x"}, msg="sm1"),
        _result("sr1", "st1"),
    ])
    _write(root / "proj" / "s" / "subagents" / "agent-orphan.jsonl", [_rec("user", "o1", "x", sessionId="s")])
    return main_path


class ReaderTests(unittest.TestCase):
    def test_events_signals_and_subagents(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = read_transcript(_transcript(Path(tmp)))
        kinds = [(e.kind, e.id) for e in session.events if not e.metadata.get("subagent")]
        self.assertIn(("interrupt", "u2"), kinds)
        meta = next(e for e in session.events if e.id == "meta")
        self.assertTrue(meta.metadata["meta"])
        self.assertEqual([e.metadata["output_tokens"] for e in session.events if e.kind == "message"
                          and e.role == "assistant" and not e.metadata.get("subagent")], [40, 50, 10, 5], "usage counted once per message")
        sub = [e for e in session.events if e.metadata.get("subagent") == "abc"]
        self.assertEqual(sub[0].parent_id, "t3")
        self.assertEqual((session.metadata["subagents_linked"], session.metadata["subagents_unlinked"]), (1, 1))
        self.assertTrue(all(SECRET not in json.dumps(e.public()) for e in session.events), "content stays out of exports")

    def test_analyze_accepts_a_claude_code_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = load_session(_transcript(Path(tmp)))
            self.assertEqual(session.format, "claude-code-v1")
            result = analyze(session)
            out = Path(tmp) / "report"
            self.assertEqual(main(["analyze", str(Path(tmp) / "proj" / "s.jsonl"), "--out", str(out)]), 0)
            self.assertNotIn(SECRET, (out / "analysis.json").read_text())
        self.assertEqual(result["metrics"]["tool_calls"], 5, "4 parent calls + 1 subagent call")

    def test_detected_after_a_long_bookkeeping_preamble(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _transcript(Path(tmp))
            body = path.read_text(encoding="utf-8")
            preamble = "".join(json.dumps({"type": "queue-operation", "operation": "enqueue"}) + "\n" for _ in range(60))
            path.write_text(preamble + body, encoding="utf-8")
            session = load_session(path)
        self.assertEqual(session.format, "claude-code-v1")
        self.assertEqual(sum(e.kind == "tool_call" for e in session.events), 5)

    def test_every_command_counts_the_same_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _transcript(root)
            workflow_steps = sum(r.steps for r in read_claude_code(root))
            request_calls = sum(len(r.calls) for r in read_requests(path))
            parent_calls = sum(e.kind == "tool_call" and not e.metadata.get("subagent")
                               for e in read_transcript(path).events)
            turns = read_turns(path)
            doc = mine(read_claude_code(root))
        self.assertEqual(workflow_steps, 4)
        self.assertEqual(request_calls, 4)
        self.assertEqual(parent_calls, 4)
        self.assertEqual([(t.id, t.author) for t in turns], [("u1", "human"), ("meta", "system"), ("u3", "human")])
        self.assertTrue(turns[2].stopped_before)
        self.assertEqual(doc["readers"], {"claude-code": "claude-code-v1"})


if __name__ == "__main__":
    unittest.main()
