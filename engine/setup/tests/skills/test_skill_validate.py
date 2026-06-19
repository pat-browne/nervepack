#!/usr/bin/env python3
"""Contract test for np-skill-validate.py — the split safety gate. Builds a
before/after skill pair and asserts exit 0 (safe) vs non-zero (revert)."""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAL = os.path.join(HERE, "..", "..", "np-skill-validate.py")

BEFORE = ("---\nname: demo\ndescription: a demo skill\n---\n"
          "Decision rule. See [[other-skill]] and [[np-core-sync]].\n" + "x" * 9000)


def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(s)


def run(skill_dir, original, split_kb="8"):
    e = dict(os.environ); e["SKILL_SPLIT_KB"] = split_kb
    return subprocess.run(["python3", VAL, skill_dir, original], env=e,
                          capture_output=True, text=True)


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = os.path.join(self.tmp, "orig.md")
        write(self.orig, BEFORE)
        self.dir = os.path.join(self.tmp, "demo")

    def _good_after(self):
        write(os.path.join(self.dir, "SKILL.md"),
              "---\nname: demo\ndescription: a demo skill\n---\n"
              "Decision rule. Detail in references/detail.md. See [[other-skill]].\n")
        write(os.path.join(self.dir, "references", "detail.md"),
              "Long detail. [[np-core-sync]]\n")

    def test_good_split_passes(self):
        self._good_after()
        self.assertEqual(run(self.dir, self.orig).returncode, 0)

    def test_body_still_too_big_fails(self):
        write(os.path.join(self.dir, "SKILL.md"), BEFORE)  # unchanged, still 9KB
        write(os.path.join(self.dir, "references", "d.md"), "x")
        self.assertNotEqual(run(self.dir, self.orig).returncode, 0)

    def test_changed_description_fails(self):
        write(os.path.join(self.dir, "SKILL.md"),
              "---\nname: demo\ndescription: DIFFERENT\n---\n"
              "Rule. references/d.md [[other-skill]] [[np-core-sync]]\n")
        write(os.path.join(self.dir, "references", "d.md"), "detail")
        self.assertNotEqual(run(self.dir, self.orig).returncode, 0)

    def test_dropped_link_fails(self):
        write(os.path.join(self.dir, "SKILL.md"),
              "---\nname: demo\ndescription: a demo skill\n---\n"
              "Rule. references/d.md [[other-skill]]\n")  # dropped [[np-core-sync]]
        write(os.path.join(self.dir, "references", "d.md"), "detail")
        self.assertNotEqual(run(self.dir, self.orig).returncode, 0)

    def test_no_references_fails(self):
        write(os.path.join(self.dir, "SKILL.md"),
              "---\nname: demo\ndescription: a demo skill\n---\n"
              "Rule only [[other-skill]] [[np-core-sync]]\n")  # no references/
        self.assertNotEqual(run(self.dir, self.orig).returncode, 0)


if __name__ == "__main__":
    unittest.main()
