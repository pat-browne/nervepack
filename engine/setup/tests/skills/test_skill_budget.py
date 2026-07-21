#!/usr/bin/env python3
"""Contract test for np_skill_budget.py (stdlib unittest, per language policy).
Black-box: builds a fake skills/ tree and asserts the emitted JSON report."""
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DET = os.path.join(HERE, "..", "..", "np_skill_budget.py")

import sys
from unittest import mock

_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_skill_budget  # noqa: E402


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


class TestSkillBudgetDirectImport(unittest.TestCase):
    """Same scenarios as TestSkillBudget, but calling scan() directly in-process
    rather than via subprocess -- proves the module is cleanly importable, which
    is the whole point of this phase's rename (Phase 10's orchestrator will call
    scan() this way, not shell out to a subprocess)."""

    def test_classifies_by_threshold_in_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_skill(tmp, "small", 3000)
            make_skill(tmp, "soft", 7000)
            make_skill(tmp, "big", 9000)
            with mock.patch.dict(os.environ, {
                "SKILL_SPLIT_KB": "8", "SKILL_SOFT_KB": "6", "SKILL_CATALOG_TOK": "4000"}):
                r = np_skill_budget.scan(tmp)
            self.assertEqual([c["skill"] for c in r["split_candidates"]], ["big"])
            self.assertEqual([c["skill"] for c in r["soft_over"]], ["soft"])

    def test_multiple_roots_first_wins_in_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root_a = os.path.join(tmp, "a"); os.makedirs(root_a)
            root_b = os.path.join(tmp, "b"); os.makedirs(root_b)
            make_skill(root_a, "dup", 1000, desc="from A")
            make_skill(root_b, "dup", 9000, desc="from B")  # would be a split-candidate if scanned
            r = np_skill_budget.scan([root_a, root_b])
            self.assertEqual(r["split_candidates"], [])  # root_a's small "dup" won, not root_b's big one


if __name__ == "__main__":
    unittest.main()
