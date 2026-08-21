#!/usr/bin/env python3
# np-test: doc-coupling | happy
"""Tests for np_doc_coupling -- the documentation-coupling check (F10/#256).

Two rules under test, and the second one is why this exists. Wen et al. (ICPC
2019) found documentation drift arrives mostly as a side effect of REFACTORING,
so a check keyed only to feature paths misses the dominant case. The
dangling-reference tests are that case.
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

import np_doc_coupling  # noqa: E402
import np_risk_tiers  # noqa: E402


def _cfg(**over):
    base = {
        "schema": 1,
        "enabled": True,
        "doc_globs": ["*.md", "docs/**", "change-specs/**"],
        "exempt_globs": ["**/tests/**"],
        "dangling_exempt_globs": ["change-specs/**"],
        "triggers": [{"id": "hooks", "globs": ["**/hooks/**"]},
                     {"id": "ci", "globs": [".github/workflows/**"]}],
    }
    base.update(over)
    return base


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestTriggers(unittest.TestCase):
    def test_a_trigger_path_fires_its_trigger(self):
        fired = np_doc_coupling.triggers_fired(["engine/hooks/x.py"], _cfg())
        self.assertEqual(fired, [("hooks", ["engine/hooks/x.py"])])

    def test_an_untriggered_path_fires_nothing(self):
        self.assertEqual(np_doc_coupling.triggers_fired(["engine/setup/misc.py"], _cfg()), [])

    def test_several_triggers_can_fire_at_once(self):
        fired = np_doc_coupling.triggers_fired(
            ["engine/hooks/x.py", ".github/workflows/ci.yml"], _cfg())
        self.assertEqual([t for t, _ in fired], ["hooks", "ci"])

    def test_a_test_only_match_does_not_fire(self):
        """Exempt paths are removed BEFORE matching. A test-only diff is
        backend-only by definition and cannot introduce user-facing behavior."""
        fired = np_doc_coupling.triggers_fired(
            ["engine/hooks/tests/test_x.py"], _cfg())
        self.assertEqual(fired, [])


class TestRuleOne(unittest.TestCase):
    def test_a_trigger_with_no_documentation_is_a_problem(self):
        with tempfile.TemporaryDirectory() as d:
            r = np_doc_coupling.evaluate(d, ["engine/hooks/x.py"], [], _cfg())
            self.assertFalse(r["satisfied"])
            self.assertTrue(any("hooks" in p for p in r["problems"]))

    def test_a_trigger_with_documentation_in_the_same_diff_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            r = np_doc_coupling.evaluate(
                d, ["engine/hooks/x.py", "docs/HOOKS.md"], [], _cfg())
            self.assertTrue(r["satisfied"], r["problems"])
            self.assertEqual(r["docs_changed"], ["docs/HOOKS.md"])

    def test_backend_only_needs_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            r = np_doc_coupling.evaluate(d, ["engine/setup/np_misc.py"], [], _cfg())
            self.assertTrue(r["satisfied"], r["problems"])

    def test_the_problem_names_the_trigger_and_the_paths(self):
        """A finding that does not say which rule fired on which file makes the
        author re-derive the check by hand."""
        with tempfile.TemporaryDirectory() as d:
            r = np_doc_coupling.evaluate(d, ["engine/hooks/x.py"], [], _cfg())
            self.assertIn("engine/hooks/x.py", r["problems"][0])


class TestRuleTwoDanglingReferences(unittest.TestCase):
    """The refactor case. A path this diff removed, still named by a document
    the diff did not touch."""

    def test_a_document_naming_a_removed_path_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "docs", "GUIDE.md"),
                   "Run `engine/setup/np_old.py` to do the thing.\n")
            r = np_doc_coupling.evaluate(
                d, ["engine/setup/np_new.py"], ["engine/setup/np_old.py"], _cfg())
            self.assertFalse(r["satisfied"])
            self.assertEqual(r["dangling"],
                             [{"removed": "engine/setup/np_old.py", "doc": "docs/GUIDE.md"}])

    def test_a_bare_basename_reference_is_found(self):
        """Documents usually name a script without its directory."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "docs", "GUIDE.md"), "See np_old.py for details.\n")
            r = np_doc_coupling.evaluate(d, [], ["engine/setup/np_old.py"], _cfg())
            self.assertEqual(len(r["dangling"]), 1)

    def test_a_longer_name_containing_the_removed_one_is_not_a_match(self):
        """np_old.py must not match inside np_older.py."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "docs", "GUIDE.md"), "See np_older.py for details.\n")
            r = np_doc_coupling.evaluate(d, [], ["engine/setup/np_old.py"], _cfg())
            self.assertEqual(r["dangling"], [])

    def test_updating_the_document_in_the_same_diff_is_clean(self):
        """The author already had it open. Flagging it would train people to
        ignore the check."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "docs", "GUIDE.md"), "np_old.py\n")
            r = np_doc_coupling.evaluate(
                d, ["docs/GUIDE.md"], ["engine/setup/np_old.py"], _cfg())
            self.assertEqual(r["dangling"], [])

    def test_a_non_document_naming_the_path_is_not_reported(self):
        """This rule is about documentation drift. A code reference to a deleted
        file is the syntax gate's problem, and it is a much louder one."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "engine", "setup", "caller.py"), "# np_old.py\n")
            r = np_doc_coupling.evaluate(d, [], ["engine/setup/np_old.py"], _cfg())
            self.assertEqual(r["dangling"], [])

    def test_removing_nothing_reports_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "docs", "GUIDE.md"), "np_old.py\n")
            r = np_doc_coupling.evaluate(d, ["engine/setup/np_new.py"], [], _cfg())
            self.assertEqual(r["dangling"], [])


class TestTheKillSwitch(unittest.TestCase):
    def test_disabled_reports_satisfied_and_checks_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            r = np_doc_coupling.evaluate(
                d, ["engine/hooks/x.py"], [], _cfg(enabled=False))
            self.assertTrue(r["satisfied"])
            self.assertFalse(r["enabled"])
            self.assertEqual(r["triggers"], [])


class TestTheCommittedConfig(unittest.TestCase):
    def test_it_loads(self):
        config = np_doc_coupling.load()
        self.assertTrue(config["triggers"])

    def test_change_specs_count_as_documentation(self):
        """A change spec is where a normal- or high-tier change explains itself.
        Requiring a second document on top of it would be ceremony."""
        config = np_doc_coupling.load()
        self.assertTrue(np_doc_coupling.is_doc("change-specs/feat-x.md", config))

    def test_tests_are_exempt(self):
        config = np_doc_coupling.load()
        self.assertTrue(np_doc_coupling.is_exempt("engine/setup/tests/x.py", config))

    def test_it_classifies_itself_high(self):
        """A trigger list that can be emptied in a standard-tier diff is not a
        trigger list."""
        registry = np_risk_tiers.load()
        for path in ("engine/setup/doc-coupling.json",
                     "engine/setup/np_doc_coupling.py",
                     "engine/setup/np-doc-coupling-gate.py"):
            self.assertEqual(np_risk_tiers.tier_for(path, registry), "high", path)

    def test_a_broken_config_raises_rather_than_checking_nothing(self):
        """An empty trigger list and an unreadable one both check nothing, and
        only one of them is a decision somebody made."""
        for bad in ("", "{not json", '{"schema": 99}',
                    '{"schema": 1, "enabled": true, "doc_globs": [], "exempt_globs": []}',
                    '{"schema": 1, "enabled": true, "doc_globs": [], "exempt_globs": [],'
                    ' "triggers": [{"id": "x"}]}'):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "doc-coupling.json")
                with open(path, "w") as f:
                    f.write(bad)
                with self.assertRaises(np_doc_coupling.ConfigError, msg=bad):
                    np_doc_coupling.load(path)



class TestAcceptedSpecsAreNeverScannedForDanglingReferences(unittest.TestCase):
    """A change spec counts as documentation for satisfying a trigger, and is
    never scanned for stale references.

    change-specs/README.md: "An accepted spec is never edited into the new
    answer." Reporting one for naming a path that has since been renamed would
    demand an edit the process forbids, and an unresolvable finding is worse
    than no finding at all."""

    def test_a_spec_naming_a_removed_path_is_not_reported(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "change-specs", "feat-old.md"),
                   "blast_radius:\n  - engine/setup/np_old.py\n")
            r = np_doc_coupling.evaluate(d, [], ["engine/setup/np_old.py"], _cfg())
            self.assertEqual(r["dangling"], [])

    def test_but_a_spec_still_satisfies_a_trigger(self):
        with tempfile.TemporaryDirectory() as d:
            r = np_doc_coupling.evaluate(
                d, ["engine/hooks/x.py", "change-specs/feat-x.md"], [], _cfg())
            self.assertTrue(r["satisfied"], r["problems"])

    def test_an_ordinary_doc_naming_the_same_path_is_still_reported(self):
        """The exemption is for change specs only, not a hole in rule 2."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "change-specs", "feat-old.md"), "np_old.py\n")
            _write(os.path.join(d, "docs", "GUIDE.md"), "np_old.py\n")
            r = np_doc_coupling.evaluate(d, [], ["engine/setup/np_old.py"], _cfg())
            self.assertEqual([x["doc"] for x in r["dangling"]], ["docs/GUIDE.md"])

    def test_the_committed_config_exempts_change_specs(self):
        config = np_doc_coupling.load()
        self.assertTrue(np_doc_coupling.is_dangling_exempt("change-specs/x.md", config))
        self.assertFalse(np_doc_coupling.is_dangling_exempt("docs/x.md", config))


if __name__ == "__main__":
    unittest.main()
