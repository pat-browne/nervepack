#!/usr/bin/env python3
# np-test: tier-policy | happy
"""Tests for np_tier_policy -- differential gating by tier (F8/#254).

This module decides how much a change has to satisfy before a human should
merge it, so the tests that matter most are the ones that catch a silent
LOOSENING: a tier that stops requiring a gate, an unknown tier that reads as
permission, or the advisory adversarial lens quietly becoming a blocking one.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_tier_policy  # noqa: E402

DETERMINISTIC = list(np_tier_policy.DETERMINISTIC_GATES)


def _all_passed(gates):
    return {g: "PASSED" for g in gates}


class TestThePolicyTable(unittest.TestCase):
    """The table in change-specs/feat-f8-tier-gate.md, asserted as data."""

    def test_standard_requires_only_the_deterministic_gates(self):
        p = np_tier_policy.policy_for("standard")
        self.assertEqual(p["required_gates"], DETERMINISTIC)
        self.assertFalse(p["rollback_required"])
        self.assertFalse(p["adversarial_lens_required"])

    def test_normal_adds_spec_guard(self):
        p = np_tier_policy.policy_for("normal")
        self.assertEqual(p["required_gates"], DETERMINISTIC + ["spec-guard"])
        self.assertFalse(p["rollback_required"])

    def test_high_adds_a_rollback_section_and_the_adversarial_lens(self):
        p = np_tier_policy.policy_for("high")
        self.assertEqual(p["required_gates"], DETERMINISTIC + ["spec-guard"])
        self.assertTrue(p["rollback_required"])
        self.assertTrue(p["adversarial_lens_required"])

    def test_the_tiers_are_monotonic(self):
        """Each tier requires everything the one below it requires. If this
        fails, some tier has become a way to require LESS by declaring MORE."""
        prev = set()
        for tier in np_tier_policy.TIERS:
            required = set(np_tier_policy.policy_for(tier)["required_gates"])
            self.assertTrue(prev <= required,
                            "%s drops a gate its predecessor required" % tier)
            prev = required

    def test_an_unknown_tier_gets_the_strictest_policy(self):
        """A typo in a spec's `tier:` field must never read as permission. The
        strictest policy is the only safe reading of 'I do not recognize this'."""
        p = np_tier_policy.policy_for("Standard")   # capital S: not a tier
        self.assertEqual(p, np_tier_policy.policy_for("high"))


class TestTheVocabularyStaysInSync(unittest.TestCase):
    """np_tier_policy states the tier names as a literal so it stays a pure
    policy module with no dependency on the registry's file I/O. That is only
    safe while the two lists agree -- a tier added to the registry and not here
    would silently take policy_for's unknown-tier branch."""

    def test_it_matches_the_registry_resolver(self):
        import np_risk_tiers
        self.assertEqual(np_tier_policy.TIERS, np_risk_tiers.TIERS)

    def test_every_tier_has_an_explicit_policy(self):
        for tier in np_tier_policy.TIERS:
            self.assertIn(tier, np_tier_policy._POLICY)

    def test_policy_for_returns_a_copy(self):
        """Callers mutate the dict on the way into JSON. A shared default would
        let one evaluation edit the next one's policy."""
        baseline = list(np_tier_policy.policy_for("standard")["required_gates"])
        first = np_tier_policy.policy_for("standard")
        first["required_gates"].append("invented-gate")
        self.assertEqual(
            np_tier_policy.policy_for("standard")["required_gates"], baseline)


class TestAutoMergeEligibility(unittest.TestCase):
    """#255 reads this field and acts on it, so a false positive here merges
    code nobody looked at."""

    def test_standard_with_every_gate_green_is_eligible(self):
        d = np_tier_policy.evaluate("standard", None, _all_passed(DETERMINISTIC))
        self.assertEqual(d["problems"], [])
        self.assertTrue(d["auto_merge_eligible"])
        self.assertEqual(d["merge_authority"], "deterministic-gates")

    def test_normal_is_never_eligible_even_when_everything_passes(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard", "diff-review"])
        d = np_tier_policy.evaluate("normal", "## Rollback\nrevert it\n", verdicts)
        self.assertEqual(d["problems"], [])
        self.assertFalse(d["auto_merge_eligible"])
        self.assertEqual(d["merge_authority"], "human")

    def test_high_is_never_eligible(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard", "diff-review"])
        d = np_tier_policy.evaluate("high", "## Rollback\nrevert it\n", verdicts)
        self.assertEqual(d["problems"], [])
        self.assertFalse(d["auto_merge_eligible"])

    def test_a_failing_gate_removes_eligibility(self):
        verdicts = _all_passed(DETERMINISTIC)
        verdicts["regression"] = "FAILED"
        d = np_tier_policy.evaluate("standard", None, verdicts)
        self.assertFalse(d["auto_merge_eligible"])
        self.assertTrue(any("regression" in p for p in d["problems"]))


class TestMissingVerdictsAreNotPasses(unittest.TestCase):
    """A gate whose verdict file never arrived must not read as PASSED. This is
    the failure mode F4's schema docstring calls out: in-toto SVR cannot express
    a negative assertion, so absence and failure look identical unless the
    consumer treats absence as a problem itself."""

    def test_an_absent_required_verdict_is_a_problem(self):
        verdicts = _all_passed(DETERMINISTIC)
        del verdicts["regression"]
        d = np_tier_policy.evaluate("standard", None, verdicts)
        self.assertFalse(d["auto_merge_eligible"])
        self.assertTrue(any("regression" in p and "no verdict" in p
                            for p in d["problems"]))

    def test_a_skipped_required_verdict_is_a_problem(self):
        verdicts = _all_passed(DETERMINISTIC)
        verdicts["pii-guard"] = "SKIPPED"
        d = np_tier_policy.evaluate("standard", None, verdicts)
        self.assertTrue(any("pii-guard" in p for p in d["problems"]))


class TestTheAdversarialLensStaysAdvisory(unittest.TestCase):
    """Measured LLM review precision is 50-85%, and the largest rejection
    category is missing project context. High tier requires the lens to have
    been APPLIED, never to have approved. If these tests ever invert, a
    50%-precision reviewer has become a blocking authority."""

    def test_high_passes_when_the_lens_ran_and_reported_findings(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard"])
        verdicts["diff-review"] = "FAILED"
        d = np_tier_policy.evaluate("high", "## Rollback\nrevert\n", verdicts)
        self.assertEqual(d["problems"], [])

    def test_high_fails_when_the_lens_did_not_run(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard"])
        verdicts["diff-review"] = "SKIPPED"
        d = np_tier_policy.evaluate("high", "## Rollback\nrevert\n", verdicts)
        self.assertTrue(any("diff-review" in p for p in d["problems"]))

    def test_high_fails_when_the_lens_verdict_is_absent_entirely(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard"])
        d = np_tier_policy.evaluate("high", "## Rollback\nrevert\n", verdicts)
        self.assertTrue(any("diff-review" in p for p in d["problems"]))

    def test_normal_does_not_require_the_lens_at_all(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard"])
        verdicts["diff-review"] = "SKIPPED"
        d = np_tier_policy.evaluate("normal", "body\n", verdicts)
        self.assertEqual(d["problems"], [])


class TestTheRollbackRequirement(unittest.TestCase):
    """High tier needs a rollback plan. An empty heading is not a plan."""

    def test_a_populated_rollback_section_satisfies_it(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard", "diff-review"])
        d = np_tier_policy.evaluate(
            "high", "# spec\n\n## Rollback\n\nRevert the commit.\n", verdicts)
        self.assertEqual(d["problems"], [])

    def test_a_missing_rollback_section_is_a_problem(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard", "diff-review"])
        d = np_tier_policy.evaluate("high", "# spec\n\n## Consequences\n\nx\n", verdicts)
        self.assertTrue(any("Rollback" in p for p in d["problems"]))

    def test_an_empty_rollback_section_is_a_problem(self):
        """`## Rollback` followed straight by the next heading is the shape a
        template leaves behind. Accepting it would make the requirement a
        formatting exercise."""
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard", "diff-review"])
        d = np_tier_policy.evaluate(
            "high", "## Rollback\n\n## Confirmation\n\nx\n", verdicts)
        self.assertTrue(any("Rollback" in p for p in d["problems"]))

    def test_the_heading_match_is_case_insensitive_and_level_agnostic(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard", "diff-review"])
        for heading in ("## rollback", "### Rollback plan", "## ROLLBACK"):
            d = np_tier_policy.evaluate(
                "high", "%s\n\nRevert it.\n" % heading, verdicts)
            self.assertEqual(d["problems"], [], heading)

    def test_a_missing_spec_is_a_problem_for_high(self):
        verdicts = _all_passed(DETERMINISTIC + ["spec-guard", "diff-review"])
        d = np_tier_policy.evaluate("high", None, verdicts)
        self.assertTrue(any("Rollback" in p or "spec" in p for p in d["problems"]))

    def test_standard_never_needs_a_spec(self):
        d = np_tier_policy.evaluate("standard", None, _all_passed(DETERMINISTIC))
        self.assertEqual(d["problems"], [])


class TestTheDecisionRecord(unittest.TestCase):
    """The dict is #255's input, so its shape is a contract, not an internal."""

    def test_it_carries_the_schema_and_the_tier(self):
        d = np_tier_policy.evaluate("high", "## Rollback\nx\n",
                                    _all_passed(DETERMINISTIC))
        self.assertEqual(d["schema"], np_tier_policy.SCHEMA)
        self.assertEqual(d["tier"], "high")

    def test_it_echoes_the_verdicts_it_judged(self):
        verdicts = _all_passed(DETERMINISTIC)
        d = np_tier_policy.evaluate("standard", None, verdicts)
        self.assertEqual(d["gate_verdicts"], verdicts)

    def test_it_lists_the_gates_it_required(self):
        d = np_tier_policy.evaluate("normal", "x\n", _all_passed(DETERMINISTIC))
        self.assertIn("spec-guard", d["required_gates"])


if __name__ == "__main__":
    unittest.main()
