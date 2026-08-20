#!/usr/bin/env python3
# np-test: risk-tiers | happy
"""Tests for np_risk_tiers -- the risk tier registry (F7/#253).

The registry decides how much scrutiny a change receives, so the tests that
matter most are the ones that catch a silent DOWNGRADE: last-match-wins being
inverted, and the self-classifying rules being shadowed by a broad glob appended
at the bottom of the file.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_risk_tiers  # noqa: E402

REPO_ROOT = os.path.normpath(os.path.join(_ENGINE_SETUP, "..", ".."))


def _reg(rules, default="normal"):
    return {"schema": 1, "default": default, "rules": rules}


class TestLastMatchWins(unittest.TestCase):
    """CODEOWNERS precedence: position in the file decides, not specificity.

    This is the opposite of most people's intuition, which is exactly why it is
    tested first.
    """

    def test_a_later_rule_overrides_an_earlier_match(self):
        reg = _reg([{"glob": "src/**", "tier": "standard"},
                    {"glob": "src/auth/**", "tier": "high"}])
        self.assertEqual(np_risk_tiers.tier_for("src/auth/login.py", reg), "high")

    def test_order_is_what_decides_not_specificity(self):
        """The same two globs in the opposite order give the opposite answer. If
        this ever passes with both orders agreeing, precedence has silently moved
        out of the data and into a tier ranking in code."""
        reg = _reg([{"glob": "src/auth/**", "tier": "high"},
                    {"glob": "src/**", "tier": "standard"}])
        self.assertEqual(np_risk_tiers.tier_for("src/auth/login.py", reg), "standard")

    def test_unmatched_path_takes_the_default(self):
        reg = _reg([{"glob": "docs/**", "tier": "standard"}], default="normal")
        self.assertEqual(np_risk_tiers.tier_for("engine/thing.py", reg), "normal")

    def test_no_rules_means_everything_is_the_default(self):
        self.assertEqual(np_risk_tiers.tier_for("anything", _reg([])), "normal")


class TestHighestOfManyPaths(unittest.TestCase):
    def test_one_high_path_makes_the_whole_diff_high(self):
        reg = _reg([{"glob": "docs/**", "tier": "standard"},
                    {"glob": "**/hooks/**", "tier": "high"}])
        files = ["docs/a.md", "docs/b.md", "engine/hooks/x.py"]
        self.assertEqual(np_risk_tiers.tier_for_paths(files, reg), "high")

    def test_all_standard_stays_standard(self):
        reg = _reg([{"glob": "docs/**", "tier": "standard"}])
        self.assertEqual(
            np_risk_tiers.tier_for_paths(["docs/a.md", "docs/b.md"], reg), "standard")

    def test_empty_diff_is_standard(self):
        """Nothing touched is nothing to protect."""
        self.assertEqual(np_risk_tiers.tier_for_paths([], _reg([])), "standard")


class TestRatchetDirection(unittest.TestCase):
    """Declaring HIGHER than required is always fine. Only under-declaring fails."""

    def test_exact_match_satisfies(self):
        self.assertTrue(np_risk_tiers.satisfies("normal", "normal"))

    def test_over_declaring_satisfies(self):
        self.assertTrue(np_risk_tiers.satisfies("high", "standard"))
        self.assertTrue(np_risk_tiers.satisfies("normal", "standard"))

    def test_under_declaring_does_not(self):
        self.assertFalse(np_risk_tiers.satisfies("standard", "high"))
        self.assertFalse(np_risk_tiers.satisfies("normal", "high"))

    def test_an_unknown_declared_tier_never_satisfies(self):
        """spec-guard validates the vocabulary separately; this must not treat an
        unrecognized word as permission."""
        self.assertFalse(np_risk_tiers.satisfies("", "normal"))
        self.assertFalse(np_risk_tiers.satisfies("lowish", "normal"))


class TestShippedRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = np_risk_tiers.load()

    def test_it_parses_and_is_the_expected_schema(self):
        self.assertEqual(self.reg["schema"], np_risk_tiers.SCHEMA)

    def test_default_is_normal(self):
        """Anything not otherwise matched needs a spec. A standard default would
        silently exempt every path nobody thought to list."""
        self.assertEqual(self.reg["default"], "normal")

    def test_every_rule_names_a_known_tier(self):
        for rule in self.reg["rules"]:
            self.assertIn(rule["tier"], np_risk_tiers.TIERS, rule)

    def test_the_registry_classifies_ITSELF_high(self):
        """The load-bearing one. If the file governing how much scrutiny every
        change receives could be edited in a standard-tier diff, it needs no spec
        and no declared tier -- a privilege escalation with the tiering mechanism
        as the vector.

        This also fails if someone appends a broad standard glob at the bottom,
        which is the file's main foreseeable mis-edit under last-match-wins.
        """
        for path in ("engine/setup/risk-tiers.json",
                     "engine/setup/np_risk_tiers.py",
                     "engine/setup/np-spec-guard.py"):
            self.assertEqual(np_risk_tiers.tier_for(path, self.reg), "high", path)

    def test_hooks_and_workflows_are_high(self):
        for path in ("engine/nervepack_engine/hooks/drift_guard.py",
                     ".github/workflows/ci.yml",
                     "engine/setup/hooks.manifest"):
            self.assertEqual(np_risk_tiers.tier_for(path, self.reg), "high", path)

    def test_the_pii_and_publish_guards_are_high(self):
        for path in ("engine/setup/np-pii-filter.py", "publish/np-publish-scan.py"):
            self.assertEqual(np_risk_tiers.tier_for(path, self.reg), "high", path)

    def test_docs_and_wiki_are_standard(self):
        for path in ("docs/ARCHITECTURE.md", "README.md",
                     "change-specs/feat-f7-risk-tiers.md"):
            self.assertEqual(np_risk_tiers.tier_for(path, self.reg), "standard", path)

    def test_ordinary_engine_code_is_normal(self):
        self.assertEqual(np_risk_tiers.tier_for("engine/setup/np_toggle.py", self.reg),
                         "normal")

    def test_it_says_the_taxonomy_is_a_synthesis(self):
        """No published standard enumerates high-risk code paths. CIS says 'extra
        sensitive code or configuration' without defining it. That honesty must
        ship in the file, not only in the change spec, or the list reads as
        authoritative."""
        self.assertIn("synthesis", self.reg.get("comment", "").lower())

    def test_high_rules_come_after_standard_rules(self):
        """Under last-match-wins, a standard glob placed after a high one silently
        downgrades everything it matches. Ordering is load-bearing, so assert it
        rather than trusting review to catch a reordering."""
        tiers = [r["tier"] for r in self.reg["rules"]]
        last_standard = max((i for i, t in enumerate(tiers) if t == "standard"),
                            default=-1)
        first_high = min((i for i, t in enumerate(tiers) if t == "high"),
                         default=len(tiers))
        self.assertLess(last_standard, first_high,
                        "a standard-tier glob appears after a high-tier one; under "
                        "last-match-wins that downgrades every path it matches")


class TestLoadFailures(unittest.TestCase):
    def test_missing_file_raises(self):
        """A CI gate whose policy file vanished must say so, not quietly treat
        everything as the default."""
        with self.assertRaises(np_risk_tiers.RegistryError):
            np_risk_tiers.load(os.path.join(tempfile.mkdtemp(), "absent.json"))

    def test_corrupt_json_raises(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "risk-tiers.json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(np_risk_tiers.RegistryError):
            np_risk_tiers.load(p)

    def test_unknown_schema_raises(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "risk-tiers.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"schema": 99, "default": "normal", "rules": []}, fh)
        with self.assertRaises(np_risk_tiers.RegistryError):
            np_risk_tiers.load(p)

    def test_malformed_glob_raises_rather_than_matching_nothing(self):
        """fnmatch does NOT raise on `[invalid` - it escapes the bracket to a
        literal, so the rule silently matches nothing. In a tier registry that is
        a silent DOWNGRADE: a typo'd high rule stops protecting anything and its
        paths fall through to the default.

        The advisory reviewer on #286 flagged this as a crash risk. It is not a
        crash; verified against five malformed patterns, none of which raised.
        The real failure is quieter and worse, so it is caught at load time."""
        d = tempfile.mkdtemp()
        p = os.path.join(d, "risk-tiers.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "default": "normal",
                       "rules": [{"glob": "**/hooks/[**", "tier": "high"}]}, fh)
        with self.assertRaises(np_risk_tiers.RegistryError):
            np_risk_tiers.load(p)

    def test_a_valid_character_class_is_still_allowed(self):
        """The check must not be a blanket ban on `[`, or it would reject working
        rules to fix a typo."""
        d = tempfile.mkdtemp()
        p = os.path.join(d, "risk-tiers.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "default": "normal",
                       "rules": [{"glob": "np-[pd]*", "tier": "high"}]}, fh)
        reg = np_risk_tiers.load(p)
        self.assertEqual(np_risk_tiers.tier_for("np-pii-filter.py", reg), "high")

    def test_unknown_tier_in_a_rule_raises(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "risk-tiers.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "default": "normal",
                       "rules": [{"glob": "x", "tier": "critical"}]}, fh)
        with self.assertRaises(np_risk_tiers.RegistryError):
            np_risk_tiers.load(p)


if __name__ == "__main__":
    unittest.main()
