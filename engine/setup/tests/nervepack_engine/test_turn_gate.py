"""Tests for hooks.turn_gate -- the Stop-event turn-completion gate."""
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

import np_turn_parse  # noqa: E402
from hooks import turn_gate  # noqa: E402


def _turn(edits=(), delivery=(), final_text=""):
    t = np_turn_parse.Turn()
    t.edits = list(edits)
    t.delivery = list(delivery)
    t.final_text = final_text
    return t


class TestTurnGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        with open(self.transcript, "w", encoding="utf-8") as fh:
            fh.write("{}\n")

    def _payload(self, **kw):
        base = {"session_id": "s1", "transcript_path": self.transcript,
                "stop_hook_active": False, "cwd": self.tmp}
        base.update(kw)
        return json.dumps(base)

    def _run(self, turn, payload=None, params=None):
        params = params or {}

        def fake_param(key, default=None):
            return params.get(key, default)

        with mock.patch.object(np_turn_parse, "parse", return_value=turn), \
             mock.patch.object(turn_gate.np_toggle, "enabled", return_value=True), \
             mock.patch.object(turn_gate.np_toggle, "param", side_effect=fake_param):
            return turn_gate.run(payload or self._payload())

    def test_ui_edit_without_delivery_blocks(self):
        out = self._run(_turn(edits=["/app/Button.tsx"]))
        data = json.loads(out)
        self.assertEqual(data["decision"], "block")
        self.assertIn("Button.tsx", data["reason"])

    def test_ui_edit_with_delivery_is_silent(self):
        self.assertEqual(self._run(_turn(edits=["/app/Button.tsx"],
                                         delivery=["read an image"])), "")

    def test_non_ui_edit_is_silent(self):
        self.assertEqual(self._run(_turn(edits=["/app/server.py"])), "")

    def test_test_fixture_paths_are_exempt(self):
        for p in ("/app/tests/page.html", "/app/__snapshots__/a.css",
                  "/app/node_modules/x/y.css", "/app/dist/a.min.css"):
            self.assertEqual(self._run(_turn(edits=[p])), "", p)

    def test_stop_hook_active_is_silent_without_parsing(self):
        with mock.patch.object(np_turn_parse, "parse",
                               side_effect=AssertionError("must not parse")):
            self.assertEqual(
                turn_gate.run(self._payload(stop_hook_active=True)), "")

    def test_toggle_off_is_silent(self):
        with mock.patch.object(turn_gate.np_toggle, "enabled", return_value=False), \
             mock.patch.object(np_turn_parse, "parse",
                               side_effect=AssertionError("must not parse")):
            self.assertEqual(turn_gate.run(self._payload()), "")

    def test_ui_param_off_disables_the_check(self):
        self.assertEqual(
            self._run(_turn(edits=["/app/a.tsx"]), params={"turn_gate.ui": "off"}), "")

    def test_ui_param_warn_warns_instead_of_blocking(self):
        out = self._run(_turn(edits=["/app/a.tsx"]), params={"turn_gate.ui": "warn"})
        data = json.loads(out)
        self.assertNotIn("decision", data)
        self.assertIn("additionalContext", data["hookSpecificOutput"])

    def test_malformed_payload_is_silent(self):
        self.assertEqual(turn_gate.run("not json"), "")

    def test_empty_payload_is_silent(self):
        self.assertEqual(turn_gate.run(""), "")

    def test_reason_names_the_ladder_and_the_escape_hatch(self):
        data = json.loads(self._run(_turn(edits=["/app/a.tsx"])))
        reason = data["reason"].lower()
        self.assertIn("screenshot", reason)
        self.assertIn("no visual", reason)


if __name__ == "__main__":
    unittest.main()
