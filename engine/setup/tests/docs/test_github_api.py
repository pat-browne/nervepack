#!/usr/bin/env python3
"""Contract test for np_github_api.py, the shared GitHub REST API fetch
helper factored out of np-gate-verdicts-comment.py once np-ledger-append.py
needed the same plumbing (F5/#251)."""
import importlib.util
import os
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))

_spec = importlib.util.spec_from_file_location(
    "np_github_api", os.path.join(SETUP, "np_github_api.py"))
np_github_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(np_github_api)


class TestDefaultFetch(unittest.TestCase):
    def test_sends_bearer_auth_and_api_version_headers(self):
        captured = {}

        class FakeResponse:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=30):
            captured["req"] = req
            return FakeResponse()

        with mock.patch.object(np_github_api.urllib.request, "urlopen", fake_urlopen):
            result = np_github_api.default_fetch("https://api.github.com/x", "tok123")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["req"].get_header("Authorization"), "Bearer tok123")
        self.assertEqual(captured["req"].get_header("X-github-api-version"), "2022-11-28")

    def test_post_sends_json_body_and_content_type(self):
        captured = {}

        class FakeResponse:
            def read(self):
                return b'{"id": 5}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=30):
            captured["req"] = req
            return FakeResponse()

        with mock.patch.object(np_github_api.urllib.request, "urlopen", fake_urlopen):
            result = np_github_api.default_fetch(
                "https://api.github.com/x", "tok", method="POST", data={"body": "hi"})

        self.assertEqual(result, {"id": 5})
        self.assertEqual(captured["req"].method, "POST")
        self.assertEqual(captured["req"].get_header("Content-type"), "application/json")

    def test_empty_response_body_returns_none(self):
        class FakeResponse:
            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(np_github_api.urllib.request, "urlopen",
                                lambda req, timeout=30: FakeResponse()):
            self.assertIsNone(np_github_api.default_fetch("https://api.github.com/x", "tok"))


if __name__ == "__main__":
    unittest.main()
