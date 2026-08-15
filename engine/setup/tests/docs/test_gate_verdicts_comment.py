#!/usr/bin/env python3
"""Contract test for np-gate-verdicts-comment.py (stdlib unittest, per
language policy). F4 in the AI-native compliance epic (#250)."""
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.abspath(os.path.join(HERE, "..", "..", "np-gate-verdicts-comment.py"))

_spec = importlib.util.spec_from_file_location("gvc", CHK)
gvc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gvc)


def _write_verdict(d, name, **overrides):
    v = {
        "schema": "nervepack.gate-verdict/1",
        "gate": name,
        "verdict": "PASSED",
        "reason": "ok",
        "evidence_ref": "http://run/%s" % name,
        "rules_sha": "abc123def456",
    }
    v.update(overrides)
    with open(os.path.join(d, "gate-verdict-%s.json" % name), "w") as f:
        json.dump(v, f)
    return v


class TestLoadVerdicts(unittest.TestCase):
    def test_loads_and_sorts_by_gate_name(self):
        with tempfile.TemporaryDirectory() as d:
            _write_verdict(d, "regression")
            _write_verdict(d, "syntax")
            verdicts = gvc.load_verdicts(d)
            self.assertEqual([v["gate"] for v in verdicts], ["regression", "syntax"])

    def test_empty_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(gvc.load_verdicts(d), [])


class TestRenderComment(unittest.TestCase):
    def test_includes_marker(self):
        body = gvc.render_comment([
            {"gate": "syntax", "verdict": "PASSED", "reason": "clean",
             "evidence_ref": "http://run", "rules_sha": "abc123def456",
             "schema": "nervepack.gate-verdict/1"},
        ])
        self.assertIn(gvc.MARKER, body)

    def test_includes_each_gate_and_reason(self):
        body = gvc.render_comment([
            {"gate": "syntax", "verdict": "PASSED", "reason": "clean",
             "evidence_ref": "http://run", "rules_sha": "abc123def456",
             "schema": "nervepack.gate-verdict/1"},
            {"gate": "regression", "verdict": "FAILED", "reason": "3 failed",
             "evidence_ref": "http://run2", "rules_sha": "abc123def456",
             "schema": "nervepack.gate-verdict/1"},
        ])
        self.assertIn("syntax", body)
        self.assertIn("clean", body)
        self.assertIn("regression", body)
        self.assertIn("3 failed", body)
        self.assertIn("FAILED", body)

    def test_no_verdicts_still_produces_a_valid_comment(self):
        body = gvc.render_comment([])
        self.assertIn(gvc.MARKER, body)


class TestFindExistingComment(unittest.TestCase):
    def test_finds_comment_carrying_marker(self):
        calls = []

        def fake_fetch(url, token, method="GET", data=None):
            calls.append((url, method))
            return [
                {"id": 1, "body": "unrelated comment"},
                {"id": 2, "body": gvc.MARKER + "\nold verdicts"},
            ]

        found = gvc.find_existing_comment("owner/repo", "42", "tok", fetch=fake_fetch)
        self.assertEqual(found, 2)
        self.assertEqual(calls[0][1], "GET")

    def test_none_when_no_marker_present(self):
        def fake_fetch(url, token, method="GET", data=None):
            return [{"id": 1, "body": "unrelated"}]

        found = gvc.find_existing_comment("owner/repo", "42", "tok", fetch=fake_fetch)
        self.assertIsNone(found)

    def test_none_on_empty_comment_list(self):
        def fake_fetch(url, token, method="GET", data=None):
            return []

        self.assertIsNone(gvc.find_existing_comment("owner/repo", "42", "tok", fetch=fake_fetch))


class TestUpsertComment(unittest.TestCase):
    def test_patches_existing_comment(self):
        calls = []

        def fake_fetch(url, token, method="GET", data=None):
            calls.append((url, method, data))
            if method == "GET":
                return [{"id": 99, "body": gvc.MARKER + "\nold"}]
            return {"id": 99}

        action, comment_id = gvc.upsert_comment("owner/repo", "7", "tok", "new body", fetch=fake_fetch)
        self.assertEqual(action, "updated")
        self.assertEqual(comment_id, 99)
        methods = [c[1] for c in calls]
        self.assertIn("PATCH", methods)
        self.assertNotIn("POST", methods)

    def test_creates_new_comment_when_none_exists(self):
        calls = []

        def fake_fetch(url, token, method="GET", data=None):
            calls.append((url, method, data))
            if method == "GET":
                return []
            return {"id": 123}

        action, comment_id = gvc.upsert_comment("owner/repo", "7", "tok", "new body", fetch=fake_fetch)
        self.assertEqual(action, "created")
        self.assertEqual(comment_id, 123)
        methods = [c[1] for c in calls]
        self.assertIn("POST", methods)
        self.assertNotIn("PATCH", methods)


class TestMainFailsOpen(unittest.TestCase):
    def test_missing_token_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            _write_verdict(d, "syntax")
            env_backup = os.environ.pop("GITHUB_TOKEN", None)
            gh_backup = os.environ.pop("GH_TOKEN", None)
            try:
                rc = gvc.main(["prog", "--verdicts-dir", d, "--repo", "owner/repo", "--pr", "1"])
            finally:
                if env_backup is not None:
                    os.environ["GITHUB_TOKEN"] = env_backup
                if gh_backup is not None:
                    os.environ["GH_TOKEN"] = gh_backup
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
