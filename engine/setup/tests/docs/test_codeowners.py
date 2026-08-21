#!/usr/bin/env python3
# np-test: codeowners | happy
"""Tests for np_codeowners -- the generated high-risk path declaration (F8/#254).

The failure this file exists to catch is a quiet one: a high-risk glob added to
risk-tiers.json and never reflected in CODEOWNERS, leaving a committed file that
claims to enumerate the sensitive paths and no longer does.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_codeowners  # noqa: E402
import np_risk_tiers  # noqa: E402

REPO_ROOT = os.path.normpath(os.path.join(_ENGINE_SETUP, "..", ".."))
COMMITTED = os.path.join(REPO_ROOT, ".github", "CODEOWNERS")


def _committed_text():
    with open(COMMITTED, encoding="utf-8") as fh:
        return fh.read()


class TestTheCommittedFileIsInSync(unittest.TestCase):
    def test_it_matches_the_generator_byte_for_byte(self):
        """Re-run `python3 engine/setup/np_codeowners.py --write` to fix."""
        text = _committed_text()
        self.assertEqual(
            np_codeowners.problems(text, np_risk_tiers.load()), [],
            "CODEOWNERS has drifted from risk-tiers.json")

    def test_every_high_tier_glob_appears_in_it(self):
        """Belt and braces on the byte comparison: if render() ever starts
        filtering, this still catches a missing high-risk path."""
        text = _committed_text()
        for rule in np_codeowners.high_tier_rules(np_risk_tiers.load()):
            self.assertIn(rule["glob"], text, rule["glob"])

    def test_no_standard_or_normal_glob_leaks_in(self):
        """A standard-tier glob in CODEOWNERS would read as a claim that docs
        are a high-risk path."""
        text = _committed_text()
        registry = np_risk_tiers.load()
        high = {r["glob"] for r in np_codeowners.high_tier_rules(registry)}
        for rule in registry["rules"]:
            if rule["glob"] in high:
                continue
            self.assertNotIn("\n%s " % rule["glob"], text, rule["glob"])
            self.assertNotIn("\n%s\t" % rule["glob"], text, rule["glob"])

    def test_it_is_under_githubs_silent_size_cap(self):
        """Past 3 MB, GitHub disables code-owner functionality for the whole
        repository with no warning of any kind."""
        self.assertLess(len(_committed_text().encode("utf-8")),
                        np_codeowners.SIZE_CAP_BYTES)


class TestTheHeaderCarriesTheCaveats(unittest.TestCase):
    """The header is the only place a reader learns that this file does not
    enforce and that its globs do not mean quite what they mean in the registry.
    Losing either sentence turns an approximation into a false claim."""

    def test_it_says_the_globs_are_copied_not_translated(self):
        text = _committed_text()
        self.assertIn("fnmatch", text)
        self.assertIn("gitignore", text)

    def test_it_says_the_approval_role_is_inert(self):
        self.assertIn("inert", _committed_text())

    def test_it_names_the_gate_that_actually_enforces(self):
        self.assertIn("np-tier-gate.py", _committed_text())

    def test_it_says_the_file_is_generated(self):
        self.assertIn("GENERATED", _committed_text())


class TestRender(unittest.TestCase):
    def test_the_catch_all_comes_before_the_high_tier_rules(self):
        """CODEOWNERS resolves last match wins. A `*` line placed after the
        specific rules would override every one of them."""
        reg = {"schema": 1, "default": "normal", "rules": [
            {"glob": "a/**", "tier": "high"}]}
        text = np_codeowners.render(reg, "@x")
        self.assertLess(text.index("\n*       @x"), text.index("\na/** "))

    def test_registry_order_is_preserved(self):
        reg = {"schema": 1, "default": "normal", "rules": [
            {"glob": "a/**", "tier": "high"},
            {"glob": "b/**", "tier": "high"}]}
        text = np_codeowners.render(reg, "@x")
        self.assertLess(text.index("a/**"), text.index("b/**"))

    def test_it_is_deterministic(self):
        reg = np_risk_tiers.load()
        self.assertEqual(np_codeowners.render(reg, "@x"),
                         np_codeowners.render(reg, "@x"))

    def test_the_owner_is_not_hardcoded_in_the_module(self):
        """The generator carries no account name of its own - it reads the
        owner off the file's `*` line."""
        with open(os.path.join(_ENGINE_SETUP, "np_codeowners.py"),
                  encoding="utf-8") as fh:
            self.assertNotIn("@pat-browne", fh.read())


class TestOwnerFrom(unittest.TestCase):
    def test_it_reads_the_catch_all_line(self):
        self.assertEqual(np_codeowners.owner_from("*       @someone\n"), "@someone")

    def test_it_reads_several_owners(self):
        self.assertEqual(np_codeowners.owner_from("*  @a @b\n"), "@a @b")

    def test_no_catch_all_line_reads_as_none(self):
        self.assertIsNone(np_codeowners.owner_from("docs/** @a\n"))

    def test_it_is_not_fooled_by_a_glob_starting_with_a_star(self):
        self.assertIsNone(np_codeowners.owner_from("*.md    @a\n"))


class TestProblems(unittest.TestCase):
    def test_drift_is_reported_with_the_fix_command(self):
        found = np_codeowners.problems("*  @x\n", np_risk_tiers.load())
        self.assertTrue(any("--write" in p for p in found))

    def test_a_file_with_no_catch_all_reports_that_first(self):
        found = np_codeowners.problems("docs/** @a\n", np_risk_tiers.load())
        self.assertEqual(len(found), 1)
        self.assertIn("catch-all", found[0])


if __name__ == "__main__":
    unittest.main()
