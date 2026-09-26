import json
import tempfile
import unittest
from pathlib import Path

from sessiongraph.cli import main
from sessiongraph.workflows import Request, family_of, mine, phase_of, read_claude_code, typical_path
from sessiongraph.worth_it import THRESHOLDS, compare, judge, judge_family

SECRET = "SECRET-PROMPT-TEXT"


def _line(**rec):
    return json.dumps(rec)


def _claude_transcript(path: Path, turns: list[list[tuple[str, dict, bool]]], day: str = "2026-09-20", command: str | None = None):
    """Write a Claude Code-like JSONL: each turn = [(tool, input, is_error), ...]."""
    lines = []
    for t, calls in enumerate(turns):
        ts = f"{day}T10:{t:02d}:00Z"
        prompt = f"{SECRET} turn {t}" if not command else f"<command-name>/{command}</command-name> {SECRET}"
        lines.append(_line(type="user", timestamp=ts, message={"role": "user", "content": prompt}))
        for i, (tool, inp, err) in enumerate(calls):
            tid = f"tu_{t}_{i}"
            lines.append(_line(type="assistant", timestamp=ts, message={
                "id": f"msg_{t}_{i}", "model": "claude-opus-5-5", "usage": {"output_tokens": 100},
                "content": [{"type": "tool_use", "id": tid, "name": tool, "input": inp}]}))
            lines.append(_line(type="user", timestamp=ts, message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "is_error": err, "content": f"{SECRET} output"}]}))
        if not calls:
            lines.append(_line(type="assistant", timestamp=ts, message={
                "id": f"msg_{t}_x", "model": "claude-opus-5-5", "usage": {"output_tokens": 400},
                "content": [{"type": "text", "text": f"{SECRET} answer"}]}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


READ = ("Read", {"file_path": f"/x/{SECRET}.py"}, False)
EDIT_FAIL = ("Edit", {"file_path": "/x/a.py"}, True)
EDIT = ("Edit", {"file_path": "/x/a.py"}, False)
TEST_FAIL = ("Bash", {"command": "npx vitest run"}, True)
TEST = ("Bash", {"command": "npm test"}, False)
COMMIT = ("Bash", {"command": "git commit -m x"}, False)
SHELL_FAIL = ("Bash", {"command": f"node {SECRET}.js"}, True)


class PhaseTests(unittest.TestCase):
    def test_phases_classify_tools_and_commands(self):
        self.assertEqual(phase_of("Read"), "explore")
        self.assertEqual(phase_of("Edit"), "edit")
        self.assertEqual(phase_of("Bash", {"command": "npx vitest run test/a.test.ts"}), "test")
        self.assertEqual(phase_of("Bash", {"command": "npm run build"}), "build")
        self.assertEqual(phase_of("Bash", {"command": "git commit -m 'x'"}), "commit")
        self.assertEqual(phase_of("Bash", {"command": "cd /a && grep -n foo b.ts"}), "explore")
        self.assertEqual(phase_of("Bash", {"command": "python3 script.py"}), "shell")
        self.assertEqual(phase_of("mcp__agentctl__agentctl_delegate"), "delegate")
        self.assertEqual(phase_of("WebFetch"), "web")

    def test_families(self):
        r = lambda phases, anchor=None: Request(session="s", harness="h", day="d", phases=phases, anchor=anchor)  # noqa: E731
        self.assertEqual(family_of(r([])), "answer-only")
        self.assertEqual(family_of(r(["explore", "explore"])), "lookup")
        self.assertEqual(family_of(r(["explore", "web"])), "research")
        self.assertEqual(family_of(r(["explore", "edit", "test"])), "edit-test")
        self.assertEqual(family_of(r(["edit", "test", "commit"])), "ship")
        self.assertEqual(family_of(r(["edit"], anchor="skill:code-review")), "skill:code-review")

    def test_typical_path_follows_the_heaviest_edges_without_loops(self):
        dfg = {"START>explore": 5, "START>edit": 1, "explore>edit": 4, "explore>END": 1, "edit>explore": 3, "edit>test": 2, "test>END": 2}
        self.assertEqual(typical_path(dfg), ["explore", "edit", "test"])


class ReaderAndGateTests(unittest.TestCase):
    def _mine(self, sessions: dict[str, tuple[list, str]], command: str | None = None):
        tmp = Path(tempfile.mkdtemp())
        for name, (turns, day) in sessions.items():
            (tmp / "proj").mkdir(exist_ok=True)
            _claude_transcript(tmp / "proj" / f"{name}.jsonl", turns, day, command)
        return tmp, read_claude_code(tmp)

    def test_reader_is_content_free_and_counts_friction_separately_from_test_failures(self):
        _, reqs = self._mine({"s1": ([[READ, EDIT_FAIL, EDIT, TEST_FAIL, TEST]], "2026-09-20")})
        self.assertEqual(len(reqs), 1)
        r = reqs[0]
        self.assertEqual(r.phases, ["explore", "edit", "edit", "test", "test"])
        self.assertEqual((r.error_steps, r.friction_errors), (2, 1))  # the failing Edit is friction; the red test is feedback
        self.assertEqual(r.error_phases, {"edit": 1, "test": 1})
        self.assertEqual(r.output_tokens, 500)
        self.assertEqual(r.model, "claude-opus-5-5")
        self.assertNotIn(SECRET, json.dumps([r.__class__.__name__, r.phases, r.anchor, r.session]))

    def test_housekeeping_commands_are_not_workflows_but_other_commands_anchor_one(self):
        _, reqs = self._mine({"s1": ([[READ]], "2026-09-20")}, command="clear")
        self.assertEqual(reqs, [])
        _, reqs = self._mine({"s1": ([[READ]], "2026-09-20")}, command="publish-garden")
        self.assertEqual(reqs[0].anchor, "/publish-garden")

    def test_gate_observe_cheap_fix_and_engineer(self):
        days = ["2026-09-20", "2026-09-21", "2026-09-22"]
        sessions = {}
        # lookups and answers: repeated, cheap per call
        for i in range(6):
            sessions[f"look{i}"] = ([[READ, READ, READ], []], days[i % 3])  # 300 tokens: above the 250 floor
        # edits with friction and erratic shapes
        shapes = [[READ, EDIT_FAIL, EDIT, SHELL_FAIL, EDIT, READ, EDIT],
                  [EDIT, SHELL_FAIL, READ, EDIT, READ, EDIT, SHELL_FAIL],
                  [READ, READ, EDIT, SHELL_FAIL, EDIT, EDIT, READ],
                  [SHELL_FAIL, EDIT, READ, EDIT, EDIT_FAIL, READ, EDIT],
                  [EDIT, READ, SHELL_FAIL, READ, EDIT, EDIT, READ]]
        for i, shape in enumerate(shapes):
            sessions[f"edit{i}"] = ([shape], days[i % 3])
        # edit-test with only failing tests (feedback, not friction)
        for i in range(5):
            sessions[f"tdd{i}"] = ([[READ, EDIT, TEST_FAIL, EDIT, TEST, COMMIT]], days[i % 3])
        _, reqs = self._mine(sessions)
        doc = judge(mine(reqs), {"levels": [
            {"effort": "low", "passRate": 1.0, "medianOutputTokens": 300},
            {"effort": "xhigh", "passRate": 1.0, "medianOutputTokens": 600}]})
        fams = {f["family"]: f for f in doc["families"]}
        self.assertEqual(fams["lookup"]["verdict"], "cheap_fix")
        self.assertIn("50% fewer output tokens", " ".join(fams["lookup"]["reasons"]))
        self.assertEqual(fams["edit"]["verdict"], "engineer")
        self.assertEqual(fams["edit"]["recommendation"]["metric"]["key"], "families.edit.friction_rate")
        self.assertEqual(fams["ship"]["verdict"], "observe")  # failing tests along the way are not friction
        self.assertIn("worth engineering", doc["gate"]["headline"])

    def test_not_enough_evidence_says_so(self):
        fam = {"family": "edit", "requests": 2, "sessions": 1, "days": 1}
        v = judge_family(fam)
        self.assertEqual(v["verdict"], "observe")
        self.assertIn("not enough evidence", v["reasons"][0])
        self.assertIn(str(int(THRESHOLDS["min_requests"])), v["reasons"][0])
        empty = judge(mine([]))
        self.assertIn("not worth applying yet", empty["gate"]["headline"])

    def test_compare_keeps_only_when_the_metric_moves_and_the_guard_holds(self):
        fam = lambda tok, err, n=6: {"family": "lookup", "median_output_tokens": tok, "error_rate": err, "requests": n}  # noqa: E731
        rec = {"metric": {"key": "families.lookup.median_output_tokens", "direction": "down"},
               "guard": {"key": "families.lookup.error_rate", "direction": "not_up"}}
        self.assertTrue(compare({"families": [fam(700, 0.05)]}, {"families": [fam(350, 0.05)]}, rec)["pass"])
        self.assertFalse(compare({"families": [fam(700, 0.05)]}, {"families": [fam(350, 0.2)]}, rec)["pass"])
        self.assertFalse(compare({"families": [fam(700, 0.05)]}, {"families": [fam(350, 0.05, n=2)]}, rec)["pass"])


class GenericReaderTests(unittest.TestCase):
    def test_agentctl_job_graphs_are_their_own_family(self):
        from sessiongraph.workflows import read_generic

        tmp = Path(tempfile.mkdtemp())
        path = tmp / "job_abc.jsonl"
        events = [
            {"id": "r", "parent_id": None, "kind": "message", "role": "user", "name": "claude:tasks", "timestamp": "2026-09-20T10:00:00Z"},
            {"id": "c1", "parent_id": "r", "kind": "tool_call", "role": "assistant", "name": "worker:codex", "timestamp": "2026-09-20T10:00:01Z"},
            {"id": "t1", "parent_id": "c1", "kind": "tool_result", "role": "tool", "name": "worker:codex", "is_error": True, "timestamp": "2026-09-20T10:00:09Z"},
        ]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        reqs = read_generic([path])
        self.assertEqual((reqs[0].harness, reqs[0].anchor, reqs[0].phases, reqs[0].error_steps), ("agentctl", "agentctl:tasks", ["delegate"], 1))
        self.assertEqual(family_of(reqs[0]), "agentctl:tasks")


class CliTests(unittest.TestCase):
    def test_workflows_cli_writes_content_free_outputs_and_compare_gates(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "proj").mkdir()
        for i, day in enumerate(["2026-09-20", "2026-09-21", "2026-09-22", "2026-09-22", "2026-09-23", "2026-09-23"]):
            _claude_transcript(tmp / "proj" / f"s{i}.jsonl", [[READ, READ, READ], [READ, READ, READ]], day)
        out = tmp / "out"
        self.assertEqual(main(["workflows", "--claude-code", str(tmp / "proj"), "--out", str(out), "--rows"]), 0)
        for name in ("workflows.json", "workflows.md", "workflows.html", "requests.json"):
            body = (out / name).read_text(encoding="utf-8")
            self.assertNotIn(SECRET, body, name)
        doc = json.loads((out / "workflows.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], "sessiongraph.workflows.v1")
        self.assertIn("pre class=\"mermaid\"", (out / "workflows.html").read_text(encoding="utf-8"))
        rec = next(f["recommendation"] for f in doc["families"] if f.get("recommendation"))
        self.assertEqual(main(["workflows-compare", str(out / "workflows.json"), str(out / "workflows.json"), "--recommendation", rec["id"]]), 1)
        self.assertEqual(main(["workflows-compare", str(out / "workflows.json"), str(out / "workflows.json"), "--recommendation", "nope"]), 2)


if __name__ == "__main__":
    unittest.main()
