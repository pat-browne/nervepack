#!/usr/bin/env python3
"""Contract test for np_skill_listing.py, the skill-listing lint.

Each failure case plants one defect in a temp skills tree and asserts the
named finding. The last class lints the real engine skills/ tree, so a long
or broken description fails the suite before it ships.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
REPO = os.path.normpath(os.path.join(SETUP, "..", ".."))
LINT = os.path.join(SETUP, "np_skill_listing.py")
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)

import np_skill_listing as L  # noqa: E402


def skill(root, name, front):
    d = os.path.join(root, name)
    os.makedirs(d)
    with open(os.path.join(d, "SKILL.md"), "w") as fh:
        fh.write(front + "\n# body\n")


def ok(root, name, desc="Use when testing."):
    skill(root, name, "---\nname: %s\ndescription: %s\n---" % (name, desc))


class TestFindings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def lint(self, **kw):
        return L.scan([self.tmp], **kw)["findings"]

    def test_clean_tree_has_no_findings(self):
        ok(self.tmp, "a")
        ok(self.tmp, "b", '"Quoted: colons are fine here."')
        skill(self.tmp, "c", "---\nname: c\ndescription: >-\n  Folded: also\n  fine.\n---")
        self.assertEqual(self.lint(), [])

    def test_missing_description(self):
        skill(self.tmp, "a", "---\nname: a\n---")
        self.assertEqual(self.lint(), ["a: missing or empty description"])

    def test_empty_description(self):
        skill(self.tmp, "a", "---\nname: a\ndescription:\n---")
        self.assertEqual(self.lint(), ["a: missing or empty description"])

    def test_no_frontmatter(self):
        skill(self.tmp, "a", "# just a heading")
        self.assertIn("a: no frontmatter block", self.lint())

    def test_plain_scalar_with_colon_is_invalid_yaml(self):
        ok(self.tmp, "a", "Use when: the parser rejects this")
        self.assertEqual(self.lint(),
                         ["a: description: plain scalar holds ': ' (quote it or use >-)"])

    def test_unterminated_quote(self):
        ok(self.tmp, "a", '"never closed')
        self.assertTrue(self.lint()[0].startswith("a: description: unterminated"))

    def test_description_over_cap(self):
        ok(self.tmp, "a", "x" * 301)
        self.assertEqual(self.lint(desc_max=300), ["a: description 301 chars > 300 cap"])
        self.assertEqual(self.lint(desc_max=301), [])

    def test_total_over_budget(self):
        ok(self.tmp, "a", "x" * 50)
        ok(self.tmp, "b", "x" * 50)
        r = L.scan([self.tmp], budget=10000)
        self.assertEqual(r["total_chars"], 2 * len("- a: " + "x" * 50) + 1)
        f = L.scan([self.tmp], budget=r["total_chars"] - 1)["findings"]
        self.assertEqual(len(f), 1)
        self.assertTrue(f[0].startswith("listing %d chars > " % r["total_chars"]))

    def test_cli_exit_codes(self):
        ok(self.tmp, "a")
        good = subprocess.run([sys.executable, LINT, self.tmp], capture_output=True)
        self.assertEqual(good.returncode, 0, good.stdout)
        ok(self.tmp, "b", "Bad: colon")
        bad = subprocess.run([sys.executable, LINT, self.tmp], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("FAIL b: description: plain scalar", bad.stdout)

    def test_host_budget_matches_claude_code(self):
        self.assertEqual(L.host_budget(200000), 8000)
        self.assertEqual(L.host_budget(1000000), 40000)


class TestEngineSkills(unittest.TestCase):
    def test_engine_skills_fit_the_listing(self):
        r = L.scan([os.path.join(REPO, "skills")])
        self.assertGreater(len(r["skills"]), 0, "engine skills/ not found")
        self.assertEqual(r["findings"], [])


if __name__ == "__main__":
    unittest.main()
