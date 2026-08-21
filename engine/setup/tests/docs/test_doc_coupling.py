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

import importlib.util  # noqa: E402
import np_doc_coupling  # noqa: E402
import np_risk_tiers  # noqa: E402

_GATE = os.path.join(_ENGINE_SETUP, "np-doc-coupling-gate.py")
_gs = importlib.util.spec_from_file_location("doc_coupling_gate", _GATE)
doc_coupling_gate = importlib.util.module_from_spec(_gs)
_gs.loader.exec_module(doc_coupling_gate)


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



class TestTheIssueBodyCannotBeInjected(unittest.TestCase):
    """Paths reach the issue body from `git diff` on a merged commit, so a file
    named `[click here](https://evil.com).md` would otherwise render as a link
    in an issue this repository opened about itself."""

    def test_a_markdown_link_in_a_path_is_rendered_as_code(self):
        result = {"triggers": [{"id": "x", "paths": ["[click](https://evil.com).md"]}],
                  "dangling": [], "docs_changed": []}
        body = doc_coupling_gate.issue_body(result, "o/r", "abc123", "")
        self.assertIn("`[click](https://evil.com).md`", body)
        self.assertNotIn("- **x** - [click](https://evil.com).md", body)

    def test_a_backtick_in_a_path_cannot_break_out_of_the_code_span(self):
        """There is no escape for a backtick inside inline code, so it is
        replaced. A backtick in a filename is pathological."""
        self.assertEqual(doc_coupling_gate._code("a`b.md"), "`a'b.md`")

    def test_a_dangling_entry_is_escaped_too(self):
        result = {"triggers": [], "docs_changed": [],
                  "dangling": [{"doc": "docs/[x](http://e).md", "removed": "a.py"}]}
        body = doc_coupling_gate.issue_body(result, "o/r", "abc", "")
        self.assertIn("`docs/[x](http://e).md`", body)


class TestFilingTheIssueFailsLoudly(unittest.TestCase):
    """Backoff is neutralised here. The retry is real, but a unit suite that
    sleeps for it teaches people to skip the suite."""

    def setUp(self):
        self._backoff = doc_coupling_gate.CREATE_BACKOFF_S
        doc_coupling_gate.CREATE_BACKOFF_S = 0

    def tearDown(self):
        doc_coupling_gate.CREATE_BACKOFF_S = self._backoff

    """This is the one step that records the debt. A silent failure here means
    the whole mechanism did nothing while looking like it worked."""

    RESULT = {"triggers": [{"id": "x", "paths": ["a.py"]}], "dangling": [],
              "docs_changed": []}

    def test_a_listing_failure_still_files(self):
        """A duplicate issue is noise. A missing one is lost debt."""
        calls = []

        def fetch(url, token, method="GET", data=None):
            calls.append((url, method))
            if method == "GET":
                raise RuntimeError("502")
            return {"number": 42}

        rc = doc_coupling_gate.open_issue("o/r", "sha", "", self.RESULT, "tok",
                                          fetch=fetch)
        self.assertEqual(rc, 0)
        self.assertIn("POST", [m for _, m in calls])

    def test_a_creation_failure_exits_one(self):
        def fetch(url, token, method="GET", data=None):
            if method == "POST":
                raise RuntimeError("500")
            return []
        self.assertEqual(
            doc_coupling_gate.open_issue("o/r", "sha", "", self.RESULT, "tok",
                                         fetch=fetch), 1)

    def test_a_response_with_no_number_exits_one(self):
        def fetch(url, token, method="GET", data=None):
            return {} if method == "POST" else []
        self.assertEqual(
            doc_coupling_gate.open_issue("o/r", "sha", "", self.RESULT, "tok",
                                         fetch=fetch), 1)

    def test_an_existing_issue_for_the_same_commit_is_not_duplicated(self):
        posted = []

        def fetch(url, token, method="GET", data=None):
            if method == "GET":
                return [{"number": 9, "body": doc_coupling_gate.MARKER + "\nsha123\n"}]
            posted.append(url)
            return {"number": 10}

        rc = doc_coupling_gate.open_issue("o/r", "sha123", "", self.RESULT, "tok",
                                          fetch=fetch)
        self.assertEqual(rc, 0)
        self.assertEqual(posted, [])

    def test_the_duplicate_search_is_narrowed_by_label(self):
        """What keeps the unpaginated 100-per-page limit from mattering."""
        seen = {}

        def fetch(url, token, method="GET", data=None):
            seen["url"] = url
            return []
        doc_coupling_gate.already_filed("o/r", "sha", "tok", fetch=fetch)
        self.assertIn("labels=%s" % doc_coupling_gate.LABEL, seen["url"])



class TestAGitFailureIsAdvisoryOnAPullRequestAndFatalAtMerge(unittest.TestCase):
    """The same condition, two right answers.

    On a pull request the check is advisory, so an unresolvable ref must not turn
    the job red over an infrastructure problem that says nothing about the diff.
    At merge time this is the step that RECORDS the debt, and returning 0 would
    forgive it silently - no issue, no finding, nothing to notice."""

    GATE = os.path.join(_ENGINE_SETUP, "np-doc-coupling-gate.py")

    def _run(self, d, *extra):
        import subprocess
        return subprocess.run(
            [sys.executable, self.GATE, "--root", d, "--base", "no-such-ref",
             "--head", "HEAD"] + list(extra),
            capture_output=True, text=True)

    def test_pull_request_mode_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            rc = self._run(d)
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            self.assertIn("could not evaluate coupling", rc.stdout)

    def test_merge_mode_exits_one(self):
        with tempfile.TemporaryDirectory() as d:
            rc = self._run(d, "--open-issue", "--repo", "o/r")
            self.assertEqual(rc.returncode, 1)
            self.assertIn("no debt was recorded", rc.stderr)

    def test_the_artifact_is_written_even_when_nothing_could_be_evaluated(self):
        """The upload step runs with if: always(), and an absent file reports as
        a confusing "no files found" rather than as the git error that happened."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "doc-coupling.json")
            self._run(d, "--out", out)
            with open(out, encoding="utf-8") as f:
                payload = json.load(f)
            self.assertFalse(payload["evaluated"])
            self.assertIn("could not resolve", payload["reason"])

    def test_the_warning_reaches_stdout_not_only_stderr(self):
        """CI job logs interleave both, but a reader scanning output for what
        happened should not have to know which stream to look at."""
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("WARNING", self._run(d).stdout)



class TestTheCreateCallRetries(unittest.TestCase):
    """GitHub documents 429 and 5xx as retryable, and this is the one call whose
    failure means the debt was never written down."""

    RESULT = {"triggers": [{"id": "x", "paths": ["a.py"]}], "dangling": [],
              "docs_changed": []}

    def setUp(self):
        self._backoff = doc_coupling_gate.CREATE_BACKOFF_S
        doc_coupling_gate.CREATE_BACKOFF_S = 0

    def tearDown(self):
        doc_coupling_gate.CREATE_BACKOFF_S = self._backoff

    def test_a_transient_failure_is_retried_and_succeeds(self):
        attempts = []

        def fetch(url, token, method="GET", data=None):
            if method == "GET":
                return []
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("503")
            return {"number": 77}

        rc = doc_coupling_gate.open_issue("o/r", "sha", "", self.RESULT, "tok",
                                          fetch=fetch)
        self.assertEqual(rc, 0)
        self.assertEqual(len(attempts), 3)

    def test_it_gives_up_after_a_bounded_number_of_attempts(self):
        attempts = []

        def fetch(url, token, method="GET", data=None):
            if method == "GET":
                return []
            attempts.append(1)
            raise RuntimeError("503")

        rc = doc_coupling_gate.open_issue("o/r", "sha", "", self.RESULT, "tok",
                                          fetch=fetch)
        self.assertEqual(rc, 1)
        self.assertEqual(len(attempts), doc_coupling_gate.CREATE_ATTEMPTS)

    def test_a_first_attempt_success_does_not_retry(self):
        attempts = []

        def fetch(url, token, method="GET", data=None):
            if method == "GET":
                return []
            attempts.append(1)
            return {"number": 1}

        doc_coupling_gate.open_issue("o/r", "sha", "", self.RESULT, "tok", fetch=fetch)
        self.assertEqual(len(attempts), 1)


class TestGitHasATimeout(unittest.TestCase):
    def test_a_timeout_reads_as_an_unresolvable_diff(self):
        """A hung git would otherwise hold the runner until the job-level
        timeout, which is measured in hours and says nothing about the cause."""
        import subprocess as sp
        real = sp.run

        def fake(argv, **kw):
            if argv[:2] == ["git", "-C"]:
                raise sp.TimeoutExpired(argv, kw.get("timeout", 1))
            return real(argv, **kw)

        sp.run = fake
        try:
            self.assertEqual(
                doc_coupling_gate.changed_and_removed(".", "a", "b"), (None, None))
        finally:
            sp.run = real

    def test_the_timeout_is_passed_to_subprocess(self):
        import subprocess as sp
        real, seen = sp.run, {}

        def fake(argv, **kw):
            seen.update(kw)
            return real(["true"], capture_output=True, text=True)

        sp.run = fake
        try:
            doc_coupling_gate.changed_and_removed(".", "a", "b")
        finally:
            sp.run = real
        self.assertEqual(seen.get("timeout"), doc_coupling_gate.GIT_TIMEOUT_S)


if __name__ == "__main__":
    unittest.main()
