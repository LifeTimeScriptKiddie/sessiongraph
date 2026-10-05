import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sessiongraph.cli import main
from sessiongraph.repos import UNKNOWN, git_root, repo_of, slugs, touched_folder
from sessiongraph.workflows import Request, mine, read_claude_code


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                   capture_output=True)


def _transcript(path: Path, cwd: str, branch: str, calls: int = 1) -> None:
    lines = [json.dumps({"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": cwd, "gitBranch": branch,
                         "sessionId": path.stem, "message": {"role": "user", "content": "do it"}})]
    for i in range(calls):
        lines.append(json.dumps({"type": "assistant", "timestamp": "2026-10-01T10:00:01Z", "message": {
            "id": f"m{i}", "usage": {"output_tokens": 10},
            "content": [{"type": "tool_use", "id": f"t{i}", "name": "Read", "input": {"file_path": "/x"}}]}}))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@unittest.skipUnless(shutil.which("git"), "git not installed")
class RepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.main = self.tmp / "proj"
        (self.main / "sub").mkdir(parents=True)
        _git(self.main, "init", "-q", "-b", "main")
        _git(self.main, "commit", "-q", "--allow-empty", "-m", "init")
        self.wt_a = self.tmp / "proj-dev-a"
        self.wt_b = self.main / ".claude" / "worktrees" / "b"
        _git(self.main, "worktree", "add", "-q", "-b", "a", str(self.wt_a))
        _git(self.main, "worktree", "add", "-q", "-b", "b", str(self.wt_b))
        git_root.cache_clear()

    def test_worktrees_and_subfolders_resolve_to_the_main_repo(self):
        for cwd in (self.main, self.main / "sub", self.wt_a, self.wt_b):
            self.assertEqual(repo_of(str(cwd)), str(self.main), cwd)

    def test_missing_cwd_is_unknown_and_a_plain_folder_is_itself(self):
        self.assertEqual(repo_of(str(self.tmp / "deleted")), UNKNOWN)
        self.assertEqual(repo_of(None), UNKNOWN)
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(repo_of(str(plain)), str(plain))

    def test_exit_check_two_worktrees_one_repo_row_and_deleted_cwd_unknown(self):
        root = self.tmp / "projects"
        _transcript(root / "p1" / "s1.jsonl", str(self.wt_a), "a")
        _transcript(root / "p2" / "s2.jsonl", str(self.wt_b), "b")
        _transcript(root / "p3" / "s3.jsonl", str(self.tmp / "gone"), "main")
        requests = read_claude_code(root)
        self.assertEqual(sorted(r.repo for r in requests), sorted([str(self.main), str(self.main), UNKNOWN]))
        self.assertEqual({r.branch for r in requests}, {"a", "b", "main"})
        doc = mine(requests, by_repo=True)
        self.assertEqual(sorted(f["family"] for f in doc["families"]), ["proj/lookup", "unknown/lookup"])
        proj = next(f for f in doc["families"] if f["family"] == "proj/lookup")
        self.assertEqual((proj["requests"], proj["branches"], proj["share"]), (2, 2, 1.0))

    def test_cli_repo_filter_and_split(self):
        root = self.tmp / "projects"
        _transcript(root / "p1" / "s1.jsonl", str(self.wt_a), "a")
        _transcript(root / "p3" / "s3.jsonl", str(self.tmp / "gone"), "main")
        out = self.tmp / "out"
        rc = main(["workflows", "--claude-code", str(root), "--repo", str(self.wt_b), "--by-repo",
                   "--allow-drift", "--out", str(out)])
        self.assertEqual(rc, 0)
        doc = json.loads((out / "workflows.json").read_text())
        self.assertEqual(doc["requests"], 1)
        self.assertEqual([f["family"] for f in doc["families"]], ["proj/lookup"])


class TouchedRepoTests(RepoTests):
    def test_session_from_a_parent_folder_takes_the_repo_its_tools_touched(self):
        root = self.tmp / "projects"
        path = root / "p" / "s.jsonl"
        lines = [json.dumps({"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.tmp),
                             "sessionId": "s", "message": {"role": "user", "content": "do it"}})]
        calls = [("Read", {"file_path": str(self.wt_a / "x.py")}), ("Bash", {"command": f"cd {self.main} && ls"}),
                 ("Bash", {"command": f"git -C {self.wt_b} status"}), ("Read", {"file_path": str(self.tmp / "y.txt")})]
        for i, (tool, inp) in enumerate(calls):
            lines.append(json.dumps({"type": "assistant", "timestamp": "2026-10-01T10:00:01Z", "cwd": str(self.tmp),
                                     "message": {"id": f"m{i}", "usage": {"output_tokens": 1}, "content": [
                                         {"type": "tool_use", "id": f"t{i}", "name": tool, "input": inp}]}}))
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        [req] = read_claude_code(root)
        self.assertEqual((req.repo, req.repo_source), (str(self.main), "touched"))

    def test_no_clear_majority_keeps_the_folder(self):
        other = self.tmp / "other"
        other.mkdir()
        _git(other, "init", "-q")
        root = self.tmp / "projects"
        path = root / "p" / "s.jsonl"
        lines = [json.dumps({"type": "user", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(self.tmp),
                             "sessionId": "s", "message": {"role": "user", "content": "do it"}})]
        for i, folder in enumerate((self.main, other)):
            lines.append(json.dumps({"type": "assistant", "timestamp": "2026-10-01T10:00:01Z", "cwd": str(self.tmp),
                                     "message": {"id": f"m{i}", "usage": {"output_tokens": 1}, "content": [
                                         {"type": "tool_use", "id": f"t{i}", "name": "Read",
                                          "input": {"file_path": str(folder / "a.py")}}]}}))
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        [req] = read_claude_code(root)
        self.assertEqual((req.repo, req.repo_source), (str(self.tmp), "folder"))

    def test_touched_folder_reads_paths_and_shell_folders(self):
        self.assertEqual(touched_folder("Bash", {"command": "git -C '/a/b' log"}, None), "/a/b")
        self.assertEqual(touched_folder("Read", {"file_path": "rel/x.py"}, "/base"), "/base/rel")
        self.assertIsNone(touched_folder("Bash", {"command": "ls"}, "/base"))


class SlugTests(unittest.TestCase):
    def test_slugs_are_unique_and_dot_free(self):
        out = slugs({"/a/x.y", "/b/tools", "/c/tools", UNKNOWN})
        self.assertEqual(out["/a/x.y"], "x-y")
        self.assertEqual({out["/b/tools"], out["/c/tools"]}, {"b-tools", "c-tools"})
        self.assertEqual(out[UNKNOWN], "unknown")

    def test_per_repo_recommendation_ids_do_not_collide(self):
        from sessiongraph.worth_it import judge
        reqs = [Request(session=f"s{i % 4}", harness="claude-code", day=f"2026-10-0{1 + i % 3}", phases=["explore"],
                        output_tokens=900, repo=repo) for repo in ("/r/one", "/r/two") for i in range(8)]
        doc = judge(mine(reqs, by_repo=True))
        ids = [f["recommendation"]["id"] for f in doc["families"] if f.get("recommendation")]
        self.assertEqual(sorted(ids), ["lookups-low-effort-one", "lookups-low-effort-two"])


if __name__ == "__main__":
    unittest.main()
