"""Tests for hooks.form_gate -- the PreToolUse durable-text form gate."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hooks import form_gate  # noqa: E402


class TestFormGatePaths(unittest.TestCase):
    def test_markdown_is_prose(self):
        self.assertTrue(form_gate._is_prose_path("/x/notes.md"))

    def test_python_is_not_prose(self):
        self.assertFalse(form_gate._is_prose_path("/x/thing.py"))

    def test_test_fixture_path_is_exempt(self):
        self.assertTrue(form_gate._is_exempt_path("/x/tests/data.md"))

    def test_voiced_prose_glob_is_exempt(self):
        globs = os.path.expanduser("~/Code/pbrowne-net/**")
        with mock.patch.object(form_gate.np_toggle, "param",
                               side_effect=lambda k, d=None:
                               globs if k == "form_gate.exempt_globs" else d):
            target = os.path.expanduser("~/Code/pbrowne-net/src/post.md")
            self.assertTrue(form_gate._is_exempt_path(target))


class TestFormGateFailOpen(unittest.TestCase):
    def _run(self, payload, enabled=True, params=None):
        params = params or {}
        with mock.patch.object(form_gate.np_toggle, "enabled", return_value=enabled), \
             mock.patch.object(form_gate.np_toggle, "param",
                               side_effect=lambda k, d=None: params.get(k, d)):
            return form_gate.run(payload)

    def test_toggle_off_returns_empty(self):
        payload = json.dumps({"tool_name": "Write",
                              "tool_input": {"file_path": "/x/a.md",
                                             "content": "a; b"}})
        self.assertEqual(self._run(payload, enabled=False), "")

    def test_malformed_payload_returns_empty(self):
        self.assertEqual(self._run("not json at all"), "")

    def test_empty_payload_returns_empty(self):
        self.assertEqual(self._run(""), "")

    def test_non_dict_payload_returns_empty(self):
        self.assertEqual(self._run("[1,2,3]"), "")

    def test_unknown_tool_returns_empty(self):
        payload = json.dumps({"tool_name": "SomeFutureTool",
                              "tool_input": {"whatever": "a; b"}})
        self.assertEqual(self._run(payload), "")


if __name__ == "__main__":
    unittest.main()
