#!/usr/bin/env python3
"""Contract test for np-diff-review.py (stdlib unittest, per language
policy). F6 in the AI-native compliance epic (#252)."""
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.abspath(os.path.join(HERE, "..", "..", "np-diff-review.py"))
for _p in (os.path.abspath(os.path.join(HERE, "..", "..")),
           os.path.abspath(os.path.join(HERE, "..", "..", "..", "nervepack_engine"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import np_model  # noqa: E402

_spec = importlib.util.spec_from_file_location("diff_review", CHK)
diff_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diff_review)


class TestModelAvailable(unittest.TestCase):
    def test_false_when_claude_bin_missing(self):
        env_backup = os.environ.pop("CLAUDE_BIN", None)
        try:
            os.environ["CLAUDE_BIN"] = "/nonexistent/claude"
            self.assertFalse(diff_review.model_available())
        finally:
            os.environ.pop("CLAUDE_BIN", None)
            if env_backup is not None:
                os.environ["CLAUDE_BIN"] = env_backup

    def test_true_when_claude_bin_executable(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"#!/bin/sh\n")
            path = f.name
        os.chmod(path, 0o755)
        env_backup = os.environ.pop("CLAUDE_BIN", None)
        try:
            os.environ["CLAUDE_BIN"] = path
            self.assertTrue(diff_review.model_available())
        finally:
            os.unlink(path)
            os.environ.pop("CLAUDE_BIN", None)
            if env_backup is not None:
                os.environ["CLAUDE_BIN"] = env_backup

    def test_true_for_non_claude_backend(self):
        backup = os.environ.get("NP_LLM_BACKEND")
        try:
            os.environ["NP_LLM_BACKEND"] = "local"
            self.assertTrue(diff_review.model_available())
        finally:
            if backup is None:
                os.environ.pop("NP_LLM_BACKEND", None)
            else:
                os.environ["NP_LLM_BACKEND"] = backup


class TestParseFindings(unittest.TestCase):
    def test_parses_bare_json_object(self):
        raw = '{"findings": [{"file": "a.py", "line": 3, "severity": "high", "comment": "bug"}]}'
        findings = diff_review.parse_findings(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["file"], "a.py")

    def test_parses_json_wrapped_in_prose_and_fences(self):
        raw = 'Sure, here you go:\n```json\n{"findings": [{"file": "b.py", "line": 1, "severity": "low", "comment": "nit"}]}\n```\nHope that helps!'
        findings = diff_review.parse_findings(raw)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["file"], "b.py")

    def test_malformed_output_returns_empty_list(self):
        self.assertEqual(diff_review.parse_findings("not json at all"), [])

    def test_missing_findings_key_returns_empty_list(self):
        self.assertEqual(diff_review.parse_findings('{"other": []}'), [])

    def test_empty_output_returns_empty_list(self):
        self.assertEqual(diff_review.parse_findings(""), [])


class TestDedupFindings(unittest.TestCase):
    def test_collapses_exact_duplicate_file_line_comment(self):
        findings = [
            {"file": "a.py", "line": 1, "severity": "high", "comment": "bug", "lens": "correctness"},
            {"file": "a.py", "line": 1, "severity": "high", "comment": "bug", "lens": "security"},
        ]
        deduped = diff_review.dedup_findings(findings)
        self.assertEqual(len(deduped), 1)

    def test_keeps_distinct_findings_on_the_same_line(self):
        # Different lenses can catch genuinely different things on one line -
        # this is not adversarial-verify consensus filtering.
        findings = [
            {"file": "a.py", "line": 1, "severity": "high", "comment": "SQL injection", "lens": "security"},
            {"file": "a.py", "line": 1, "severity": "low", "comment": "unclear name", "lens": "maintainer"},
        ]
        deduped = diff_review.dedup_findings(findings)
        self.assertEqual(len(deduped), 2)


class TestDiffLinePositions(unittest.TestCase):
    def test_extracts_valid_right_side_lines_from_a_hunk(self):
        patch = "@@ -10,3 +10,4 @@ def foo():\n context\n-old\n+new1\n+new2\n context2"
        positions = diff_review.diff_line_positions(patch)
        # RIGHT side numbering starts at 10: context=10, new1=11, new2=12, context2=13
        self.assertEqual(positions, {10, 11, 12, 13})

    def test_empty_patch_returns_empty_set(self):
        self.assertEqual(diff_review.diff_line_positions(""), set())

    def test_multiple_hunks(self):
        patch = "@@ -1,1 +1,1 @@\n context\n@@ -20,1 +21,2 @@\n context\n+added"
        positions = diff_review.diff_line_positions(patch)
        self.assertEqual(positions, {1, 21, 22})


class TestBuildReviewComments(unittest.TestCase):
    def test_finding_on_valid_line_becomes_inline_comment(self):
        findings = [{"file": "a.py", "line": 11, "severity": "high",
                     "comment": "bug", "lens": "correctness"}]
        file_patches = {"a.py": "@@ -10,1 +10,2 @@\n context\n+new1"}
        comments, unplaced = diff_review.build_review_comments(findings, file_patches)
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["path"], "a.py")
        self.assertEqual(comments[0]["line"], 11)
        self.assertEqual(unplaced, [])

    def test_finding_on_invalid_line_is_unplaced(self):
        findings = [{"file": "a.py", "line": 999, "severity": "high",
                     "comment": "bug", "lens": "correctness"}]
        file_patches = {"a.py": "@@ -10,1 +10,2 @@\n context\n+new1"}
        comments, unplaced = diff_review.build_review_comments(findings, file_patches)
        self.assertEqual(comments, [])
        self.assertEqual(len(unplaced), 1)

    def test_finding_on_file_not_in_patch_set_is_unplaced(self):
        findings = [{"file": "missing.py", "line": 1, "severity": "low",
                     "comment": "x", "lens": "correctness"}]
        comments, unplaced = diff_review.build_review_comments(findings, {})
        self.assertEqual(comments, [])
        self.assertEqual(len(unplaced), 1)


class TestBuildVerdict(unittest.TestCase):
    def test_no_findings_is_passed(self):
        v = diff_review.build_verdict([], "http://run", "abc123")
        self.assertEqual(v["verdict"], "PASSED")

    def test_findings_still_passed_never_failed_for_content(self):
        # This gate never fails the build over review content - only over the
        # review PROCESS erroring. Findings existing is not a failure.
        findings = [{"file": "a.py", "line": 1, "severity": "high",
                     "comment": "x", "lens": "correctness"}]
        v = diff_review.build_verdict(findings, "http://run", "abc123")
        self.assertEqual(v["verdict"], "PASSED")
        self.assertIn("1 finding", v["reason"])

    def test_shape_matches_f4_schema(self):
        v = diff_review.build_verdict([], "http://run", "abc123")
        self.assertEqual(v["gate"], "diff-review")
        self.assertEqual(v["evidence_ref"], "http://run")
        self.assertEqual(v["rules_sha"], "abc123")
        self.assertIn("schema", v)


class TestPostReview(unittest.TestCase):
    def test_event_is_always_comment_never_approve_or_request_changes(self):
        captured = {}

        def fake_fetch(url, token, method="GET", data=None):
            captured["data"] = data
            return {"id": 1}

        diff_review.post_review("owner/repo", "7", "tok", "body text", [], fetch=fake_fetch)
        self.assertEqual(captured["data"]["event"], "COMMENT")

    def test_comments_included_in_payload(self):
        captured = {}

        def fake_fetch(url, token, method="GET", data=None):
            captured["data"] = data
            return {"id": 1}

        comments = [{"path": "a.py", "line": 1, "side": "RIGHT", "body": "x"}]
        diff_review.post_review("owner/repo", "7", "tok", "body", comments, fetch=fake_fetch)
        self.assertEqual(captured["data"]["comments"], comments)


class TestBuildContext(unittest.TestCase):
    def test_reads_spec_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "change-specs"))
            with open(os.path.join(d, "change-specs", "feat-x.md"), "w") as f:
                f.write("---\nid: 1\n---\nspec body")
            spec_text, _ = diff_review.build_context(d, "change-specs/feat-x.md")
            self.assertIn("spec body", spec_text)

    def test_none_when_spec_absent(self):
        with tempfile.TemporaryDirectory() as d:
            spec_text, _ = diff_review.build_context(d, "change-specs/does-not-exist.md")
            self.assertIsNone(spec_text)


class TestMainHappyPath(unittest.TestCase):
    def test_full_run_posts_review_and_writes_verdict(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"#!/bin/sh\n")
            claude_stub = f.name
        os.chmod(claude_stub, 0o755)
        os.environ["CLAUDE_BIN"] = claude_stub
        os.environ["GITHUB_TOKEN"] = "tok"

        posted = {}

        def fake_fetch(url, token, method="GET", data=None):
            if "pulls" in url and url.endswith("/files?per_page=100"):
                return [{"filename": "a.py",
                          "patch": "@@ -1,1 +1,2 @@\n context\n+new_line"}]
            if method == "POST" and "reviews" in url:
                posted["data"] = data
                return {"id": 1}
            return []

        def fake_complete(prompt, system=None, timeout=None):
            # Every lens "finds" the same one thing, on the valid new line -
            # dedup should collapse identical (file, line, comment) findings.
            return '{"findings": [{"file": "a.py", "line": 2, "severity": "low", "comment": "note"}]}'

        with tempfile.TemporaryDirectory() as repo_root:
            try:
                rc = diff_review.main(
                    ["prog", "--repo", "owner/repo", "--pr", "9",
                     "--repo-root", repo_root, "--branch", "feat/thing",
                     "--evidence-ref", "http://run", "--rules-sha", "sha123",
                     "--out", os.path.join(repo_root, "verdict.json")],
                    fetch=fake_fetch, complete=fake_complete,
                )
            finally:
                os.unlink(claude_stub)
                os.environ.pop("CLAUDE_BIN", None)
                os.environ.pop("GITHUB_TOKEN", None)

            self.assertEqual(rc, 0)
            self.assertEqual(posted["data"]["event"], "COMMENT")
            self.assertEqual(len(posted["data"]["comments"]), 1)  # deduped from 4 lenses to 1

            with open(os.path.join(repo_root, "verdict.json")) as vf:
                verdict = json.load(vf)
            self.assertEqual(verdict["verdict"], "PASSED")
            self.assertEqual(verdict["gate"], "diff-review")


class TestMainFailsOpenOnNoModel(unittest.TestCase):
    def test_skips_cleanly_when_claude_unavailable(self):
        os.environ["CLAUDE_BIN"] = "/nonexistent/claude"
        try:
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "verdict.json")
                rc = diff_review.main([
                    "prog", "--repo", "owner/repo", "--pr", "1",
                    "--repo-root", ".", "--base", "main", "--head", "HEAD",
                    "--branch", "feat/thing", "--out", out,
                ])
                self.assertTrue(os.path.isfile(out))
        finally:
            os.environ.pop("CLAUDE_BIN", None)
        self.assertEqual(rc, 0)


class TestCiJobIsActuallyWired(unittest.TestCase):
    """The gate reported SKIPPED on every PR ever opened, because the job never
    installed the CLI and never passed the secret -- while change-spec 0006 said
    it was one secret away from running. These assertions exist so that claim
    cannot go stale again silently: drop any of the three and a test fails.
    """

    @classmethod
    def setUpClass(cls):
        root = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
        with open(os.path.join(root, ".github", "workflows", "ci.yml"),
                  encoding="utf-8") as fh:
            text = fh.read()
        cls.job = text.split("  diff-review:", 1)[1].split("\n  gate-verdicts-summary:", 1)[0]

    def test_installs_the_claude_cli(self):
        self.assertIn("@anthropic-ai/claude-code@", self.job)

    def test_pins_the_cli_version(self):
        """A floating version changes the reviewer between two runs of one PR,
        which is what F4's rules_sha pinning exists to prevent."""
        m = re.search(r"@anthropic-ai/claude-code@(\S+)", self.job)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"^\d+\.\d+\.\d+$")

    def test_exports_claude_bin_for_the_probe(self):
        """np-diff-review.py's model_available() reads CLAUDE_BIN; without it
        the probe looks in ~/.local/bin, where npm does not install."""
        self.assertIn("CLAUDE_BIN=", self.job)

    def test_passes_the_oauth_token_into_the_review_step(self):
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
                      self.job)

    def test_stays_advisory(self):
        """This change activates the reviewer. It must not promote it."""
        self.assertIn("continue-on-error: true", self.job)


class TestFailsOpenOnAuthError(unittest.TestCase):
    """Installing the CLI in CI moved the failure, it did not remove it.

    Before: no CLI, model_available() False, clean SKIPPED. After: CLI present,
    no credential, np_model.complete() raises AuthError out of the lens loop,
    traceback, non-zero exit, red job. That is exactly the fork-PR case -- forks
    never receive secrets -- so without this the advisory gate would fail every
    fork PR it was built to stay out of the way of.
    """

    def _run(self, exc):
        def boom(prompt, *a, **kw):
            raise exc

        def fake_fetch(url, token, method="GET", data=None):
            if "/files" in url:
                return [{"filename": "a.py", "patch": "@@ -1 +1 @@\n-a\n+b"}]
            return {}

        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "verdict.json")
            os.environ["CLAUDE_BIN"] = sys.executable  # a real executable: probe passes
            os.environ["GITHUB_TOKEN"] = "t"
            try:
                rc = diff_review.main([
                    "prog", "--repo", "owner/repo", "--pr", "1",
                    "--repo-root", ".", "--base", "main", "--head", "HEAD",
                    "--branch", "feat/thing", "--out", out,
                ], fetch=fake_fetch, complete=boom)
            finally:
                os.environ.pop("CLAUDE_BIN", None)
                os.environ.pop("GITHUB_TOKEN", None)
            with open(out) as fh:
                return rc, json.load(fh)

    def test_auth_error_exits_zero(self):
        rc, _ = self._run(np_model.AuthError("Invalid API key"))
        self.assertEqual(rc, 0)

    def test_auth_error_records_skipped_not_failed(self):
        """SKIPPED means the gate never ran. FAILED would assert the diff is
        bad, which is a lie the ledger would carry forever."""
        _, verdict = self._run(np_model.AuthError("Invalid API key"))
        self.assertEqual(verdict["verdict"], "SKIPPED")

    def test_auth_error_reason_is_actionable(self):
        _, verdict = self._run(np_model.AuthError("Invalid API key"))
        self.assertIn("credential", verdict["reason"].lower())

    def test_any_backend_failure_also_fails_open(self):
        rc, verdict = self._run(OSError("claude: command hung"))
        self.assertEqual(rc, 0)
        self.assertEqual(verdict["verdict"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()
