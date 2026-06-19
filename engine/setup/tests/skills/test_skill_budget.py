#!/usr/bin/env python3
"""Contract test for np-skill-budget.py (stdlib unittest, per language policy).
Black-box: builds a fake skills/ tree and asserts the emitted JSON report."""
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DET = os.path.join(HERE, "..", "..", "np-skill-budget.py")


def make_skill(root, name, body_bytes, desc="a short skill description"):
    d = os.path.join(root, name)
    os.makedirs(d)
    fm = "---\nname: %s\ndescription: %s\n---\n" % (name, desc)
    pad = "x" * max(0, body_bytes - len(fm.encode()))
    with open(os.path.join(d, "SKILL.md"), "w") as fh:
        fh.write(fm + pad)


def run(skills_dir, **env):
    e = dict(os.environ); e.update(env)
    out = subprocess.run(["python3", DET, skills_dir], env=e,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class TestSkillBudget(unittest.TestCase):
    def test_classifies_by_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_skill(tmp, "small", 3000)
            make_skill(tmp, "soft", 7000)    # > 6KB, <= 8KB
            make_skill(tmp, "big", 9000)     # > 8KB
            r = run(tmp, SKILL_SPLIT_KB="8", SKILL_SOFT_KB="6", SKILL_CATALOG_TOK="4000")
            self.assertEqual([c["skill"] for c in r["split_candidates"]], ["big"])
            self.assertEqual([c["skill"] for c in r["soft_over"]], ["soft"])

    def test_thresholds_are_tunable(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_skill(tmp, "mid", 7000)
            r = run(tmp, SKILL_SPLIT_KB="6")  # lower the bar
            self.assertEqual([c["skill"] for c in r["split_candidates"]], ["mid"])

    def test_catalog_over_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_skill(tmp, "a", 1000, desc="d" * 9000)  # ~2250 tok of description
            make_skill(tmp, "b", 1000, desc="d" * 9000)
            r = run(tmp, SKILL_CATALOG_TOK="4000")
            self.assertTrue(r["catalog_over"])
            self.assertGreater(r["catalog_tokens"], 4000)

    def test_missing_dir_fail_open(self):
        r = run("/nonexistent/skills")
        self.assertEqual(r["split_candidates"], [])
        self.assertFalse(r["catalog_over"])


if __name__ == "__main__":
    unittest.main()
