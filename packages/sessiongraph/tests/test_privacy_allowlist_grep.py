"""CI grep: agentctl job readers must not retain deny-listed bodies."""

from __future__ import annotations

import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "sessiongraph"
DENY_NEEDLES = ("normalizedText", "route-log.jsonl")
# stdout may appear in deny comments / drop lists; require it only paired with a retain pattern.
READER_FILES = ("agentctl_jobs.py", "failures.py", "failure_tags.py")


class PrivacyAllowListGrepTests(unittest.TestCase):
    def test_readers_do_not_open_input_json(self) -> None:
        for name in READER_FILES:
            text = (SRC / name).read_text(encoding="utf-8")
            # May mention input.json in comments / DENY_FILES, but must not read it.
            self.assertNotRegex(
                text,
                r"""(?:open|read_text|read_bytes)\([^)]*input\.json""",
            )

    def test_deny_needles_only_in_drop_context(self) -> None:
        text = (SRC / "agentctl_jobs.py").read_text(encoding="utf-8")
        for needle in DENY_NEEDLES:
            self.assertIn(needle, text)  # documented deny
        # Must not assign from these keys onto the projected record.
        self.assertNotRegex(text, r"""out\[[^\]]*normalizedText""")
        self.assertNotRegex(text, r"""\[['\"]stdout['\"]\]\s*=""")


if __name__ == "__main__":
    unittest.main()
