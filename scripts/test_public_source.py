"""Synthetic checks for the public-source gate; never use real credentials."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("public_source", Path(__file__).with_name("check-public-source.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class PublicSourceTests(unittest.TestCase):
    def test_blocks_private_paths_without_echoing_contents(self):
        home = "/" + "Users" + "/" + "synthetic-person" + "/" + "private-project"
        result = guard.inspect_file("sample.py", home.encode())
        self.assertEqual(len(result), 1)
        self.assertNotIn(home, " ".join(result))

    def test_blocks_runtime_files_and_unknown_binary(self):
        for name in (".iseeagents/capture.jsonl", ".env", "data.sqlite"):
            self.assertTrue(guard.inspect_file(name, b"{}"))
        self.assertTrue(guard.inspect_file("image.bin", bytes([255])))

    def test_allows_synthetic_examples(self):
        self.assertEqual(guard.inspect_file("tests/fixtures/session.jsonl", b'{"email":"user@example.invalid"}'), [])

    def test_flags_tokens_without_echoing_them(self):
        token = "gh" + "p_" + "A" * 36
        result = guard.inspect_file("config.txt", token.encode())
        self.assertTrue(result)
        self.assertNotIn(token, " ".join(result))

    def test_rejects_unreviewed_session_capture(self):
        self.assertTrue(guard.inspect_file("capture.jsonl", b"{}"))


if __name__ == "__main__":
    unittest.main()
