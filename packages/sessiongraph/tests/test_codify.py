import json
import tempfile
import unittest
from pathlib import Path

from sessiongraph.cli import main
from sessiongraph.codify import codify, install
from sessiongraph.worth_it import compare

FAMILY = {"family": "ship:edit-test", "base_family": "ship:edit-test", "requests": 21, "sessions": 9, "days": 7,
          "friction_rate": 0.476, "median_steps": 44, "variant_count": 14, "error_phases": {"shell": 12, "test": 7},
          "recommendation": {"id": "codify-ship-edit-test",
                             "metric": {"key": "families.ship:edit-test.friction_rate", "direction": "down"},
                             "guard": {"key": "families.ship:edit-test.median_steps", "direction": "not_up"}}}


class CodifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.before = self.tmp / "before.json"
        self.before.write_text(json.dumps({"families": [FAMILY]}))

    def test_skill_follows_the_definition_and_records_provenance(self):
        made = codify(json.loads(self.before.read_text()), "ship:edit-test", self.tmp / "skills", baseline_path=self.before)
        body = (Path(made["folder"]) / "SKILL.md").read_text()
        self.assertTrue(body.startswith('---\nname: ship-edit-test\ndescription: "'))
        order = [body.index(f"**{p}**") for p in ("explore", "edit", "commit")]
        self.assertEqual(order, sorted(order))
        self.assertIn("No commit before a passing check", body)
        self.assertIn("21 requests in 9 sessions", body)
        prov = json.loads((Path(made["folder"]) / "provenance.json").read_text())
        self.assertEqual(prov["after_family"], "skill:ship-edit-test")
        self.assertIn("--after-family skill:ship-edit-test", prov["compare"])
        with self.assertRaises(ValueError):  # the baseline is never regenerated over
            codify(json.loads(self.before.read_text()), "ship:edit-test", self.tmp / "skills")

    def test_unknown_family_kind_is_refused(self):
        doc = {"families": [{**FAMILY, "family": "lookup", "base_family": "lookup"}]}
        with self.assertRaises(ValueError):
            codify(doc, "lookup", self.tmp / "skills")

    def test_install_links_one_folder_and_never_replaces_another(self):
        made = codify(json.loads(self.before.read_text()), "ship:edit-test", self.tmp / "skills")
        dirs = {"a": str(self.tmp / "a"), "b": str(self.tmp / "b")}
        (self.tmp / "b" / "ship-edit-test").mkdir(parents=True)
        result = install(Path(made["folder"]), dirs)
        self.assertTrue(result["a"].startswith("linked"))
        self.assertTrue(result["b"].startswith("skipped"))
        self.assertEqual((self.tmp / "a" / "ship-edit-test").resolve(), Path(made["folder"]).resolve())
        self.assertEqual(install(Path(made["folder"]), dirs)["a"], "already linked")

    def test_compare_reads_the_after_side_from_the_skill_family(self):
        after = {"families": [{"family": "skill:ship-edit-test", "requests": 8, "friction_rate": 0.2, "median_steps": 30}]}
        result = compare({"families": [FAMILY]}, after, FAMILY["recommendation"], "skill:ship-edit-test")
        self.assertTrue(result["pass"], result)
        self.assertFalse(compare({"families": [FAMILY]}, after, FAMILY["recommendation"])["pass"])

    def test_cli(self):
        rc = main(["codify", str(self.before), "--family", "ship:edit-test", "--out", str(self.tmp / "skills")])
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmp / "skills" / "ship-edit-test" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
