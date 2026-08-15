#!/usr/bin/env python3
"""Contract test for np-ledger-append.py (stdlib unittest, per language
policy). F5 in the AI-native compliance epic (#251)."""
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.abspath(os.path.join(HERE, "..", "..", "np-ledger-append.py"))

_spec = importlib.util.spec_from_file_location("ledger_append", CHK)
ledger_append = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger_append)


class TestGatesFromVerdicts(unittest.TestCase):
    def test_trims_each_verdict_to_name_verdict_rules_sha(self):
        verdicts = [
            {"schema": "nervepack.gate-verdict/1", "gate": "syntax",
             "verdict": "PASSED", "reason": "clean", "evidence_ref": "http://x",
             "rules_sha": "abc123"},
        ]
        self.assertEqual(
            ledger_append.gates_from_verdicts(verdicts),
            [{"name": "syntax", "verdict": "PASSED", "rules_sha": "abc123"}],
        )

    def test_empty_list_stays_empty(self):
        self.assertEqual(ledger_append.gates_from_verdicts([]), [])


class TestBuildEntry(unittest.TestCase):
    def test_shape_matches_the_issues_example(self):
        entry = ledger_append.build_entry(
            change_id="feat-f5-thing",
            spec="change-specs/feat-f5-thing.md",
            tier="normal",
            diff_sha="head123",
            gates=[{"name": "regression", "verdict": "PASSED", "rules_sha": "abc"}],
            merge_sha="merge456",
            ts="2026-08-15T00:00:00+00:00",
        )
        self.assertEqual(entry["change_id"], "feat-f5-thing")
        self.assertEqual(entry["spec"], "change-specs/feat-f5-thing.md")
        self.assertEqual(entry["tier"], "normal")
        self.assertEqual(entry["diff_sha"], "head123")
        self.assertEqual(entry["gates"][0]["name"], "regression")
        self.assertEqual(entry["merge_sha"], "merge456")
        self.assertEqual(entry["ts"], "2026-08-15T00:00:00+00:00")


class TestAppendEntry(unittest.TestCase):
    def test_appends_one_json_line_creating_parent_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dashboard", "data", "ledger.jsonl")
            ledger_append.append_entry(path, {"change_id": "a"})
            ledger_append.append_entry(path, {"change_id": "b"})
            with open(path) as f:
                lines = [json.loads(line) for line in f if line.strip()]
            self.assertEqual([l["change_id"] for l in lines], ["a", "b"])

    def test_never_overwrites_prior_entries(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ledger.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"change_id": "existing"}) + "\n")
            ledger_append.append_entry(path, {"change_id": "new"})
            with open(path) as f:
                lines = [json.loads(line) for line in f if line.strip()]
            self.assertEqual([l["change_id"] for l in lines], ["existing", "new"])


class TestExtractVerdictsJsonMirror(unittest.TestCase):
    """A small, deliberate duplicate of np-gate-verdicts-comment.py's
    extract_verdicts_json - see that module's docstring for why this isn't
    a cross-script import."""

    def test_extracts_embedded_json(self):
        body = "some text\n<!-- nervepack:gate-verdicts-json\n[{\"gate\": \"syntax\"}]\n-->"
        self.assertEqual(
            ledger_append.extract_verdicts_json(body), [{"gate": "syntax"}])

    def test_none_when_absent(self):
        self.assertIsNone(ledger_append.extract_verdicts_json("no marker here"))

    def test_none_on_malformed(self):
        body = "<!-- nervepack:gate-verdicts-json\nnot json\n-->"
        self.assertIsNone(ledger_append.extract_verdicts_json(body))


class TestFetchPrMeta(unittest.TestCase):
    def test_extracts_head_sha_head_ref_and_merge_sha(self):
        def fake_fetch(url, token, method="GET", data=None):
            return {
                "head": {"sha": "headsha123", "ref": "feat/thing"},
                "merge_commit_sha": "mergesha456",
            }

        meta = ledger_append.fetch_pr_meta("owner/repo", "7", "tok", fetch=fake_fetch)
        self.assertEqual(meta["head_sha"], "headsha123")
        self.assertEqual(meta["head_ref"], "feat/thing")
        self.assertEqual(meta["merge_sha"], "mergesha456")


class TestFindGateVerdictsCommentBody(unittest.TestCase):
    def test_finds_comment_body_containing_the_json_marker(self):
        def fake_fetch(url, token, method="GET", data=None):
            return [
                {"id": 1, "body": "unrelated"},
                {"id": 2, "body": "<!-- nervepack:gate-verdicts -->\nstuff\n"
                                  "<!-- nervepack:gate-verdicts-json\n[]\n-->"},
            ]

        body = ledger_append.find_gate_verdicts_comment_body(
            "owner/repo", "7", "tok", fetch=fake_fetch)
        self.assertIn("gate-verdicts-json", body)

    def test_none_when_no_comment_has_the_marker(self):
        def fake_fetch(url, token, method="GET", data=None):
            return [{"id": 1, "body": "unrelated"}]

        self.assertIsNone(
            ledger_append.find_gate_verdicts_comment_body("owner/repo", "7", "tok", fetch=fake_fetch))


class TestMainFailureModes(unittest.TestCase):
    def test_missing_token_returns_one(self):
        env_backup = os.environ.pop("GITHUB_TOKEN", None)
        gh_backup = os.environ.pop("GH_TOKEN", None)
        try:
            rc = ledger_append.main(
                ["prog", "--repo", "owner/repo", "--pr", "1",
                 "--content-dir", "/tmp/does-not-matter"])
        finally:
            if env_backup is not None:
                os.environ["GITHUB_TOKEN"] = env_backup
            if gh_backup is not None:
                os.environ["GH_TOKEN"] = gh_backup
        self.assertEqual(rc, 1)

    def test_missing_content_dir_returns_one(self):
        os.environ["GITHUB_TOKEN"] = "tok"
        cd_backup = os.environ.pop("NP_CONTENT_DIR", None)
        try:
            rc = ledger_append.main(["prog", "--repo", "owner/repo", "--pr", "1"])
        finally:
            os.environ.pop("GITHUB_TOKEN", None)
            if cd_backup is not None:
                os.environ["NP_CONTENT_DIR"] = cd_backup
        self.assertEqual(rc, 1)

    def test_missing_spec_file_is_not_an_error_standard_tier_may_have_none(self):
        with tempfile.TemporaryDirectory() as repo_root, \
                tempfile.TemporaryDirectory() as content_dir:
            os.environ["GITHUB_TOKEN"] = "tok"

            def fake_fetch(url, token, method="GET", data=None):
                if "pulls" in url:
                    return {"head": {"sha": "h", "ref": "docs/no-spec-needed"},
                            "merge_commit_sha": "m"}
                return []

            try:
                rc = ledger_append.main(
                    ["prog", "--repo", "owner/repo", "--pr", "1",
                     "--repo-root", repo_root, "--content-dir", content_dir],
                    fetch=fake_fetch,
                )
            finally:
                os.environ.pop("GITHUB_TOKEN", None)
            self.assertEqual(rc, 0)
            ledger_path = os.path.join(content_dir, "dashboard", "data", "ledger.jsonl")
            self.assertFalse(os.path.isfile(ledger_path))


if __name__ == "__main__":
    unittest.main()
