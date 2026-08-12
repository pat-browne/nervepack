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
        with mock.patch.object(np_turn_parse, "parse") as parse_mock:
            self.assertEqual(
                turn_gate.run(self._payload(stop_hook_active=True)), "")
            parse_mock.assert_not_called()

    def test_toggle_off_is_silent(self):
        with mock.patch.object(turn_gate.np_toggle, "enabled", return_value=False), \
             mock.patch.object(np_turn_parse, "parse") as parse_mock:
            self.assertEqual(turn_gate.run(self._payload()), "")
            parse_mock.assert_not_called()

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

    def test_markdown_edit_without_diff_warns(self):
        out = self._run(_turn(edits=["/docs/guide.md"]))
        data = json.loads(out)
        self.assertIn("np-flow-deliver-diff",
                      data["hookSpecificOutput"]["additionalContext"])
        self.assertIn("guide.md", data["hookSpecificOutput"]["additionalContext"])

    def test_markdown_edit_with_diff_is_silent(self):
        turn = _turn(edits=["/docs/guide.md"], delivery=["ran np-md-diff.py"])
        self.assertEqual(self._run(turn), "")

    def test_spec_and_plan_docs_are_exempt_from_diff(self):
        for p in ("/c/docs/superpowers/specs/x-design.md",
                  "/c/docs/superpowers/plans/x.md"):
            self.assertEqual(self._run(_turn(edits=[p])), "", p)

    def test_form_warn_when_linter_scores_above_threshold(self):
        turn = _turn(final_text="prose")
        with mock.patch.object(turn_gate, "_lint_score",
                               return_value=(30.0, [("em_dash", 9)])):
            data = json.loads(self._run(turn, params={"turn_gate.form_threshold": "12"}))
        self.assertIn("em_dash", data["hookSpecificOutput"]["additionalContext"])

    def test_form_silent_when_below_threshold(self):
        turn = _turn(final_text="prose")
        with mock.patch.object(turn_gate, "_lint_score", return_value=(3.0, [])):
            self.assertEqual(self._run(turn,
                                       params={"turn_gate.form_threshold": "12"}), "")

    def test_form_silent_when_linter_missing(self):
        turn = _turn(final_text="prose")
        with mock.patch.object(turn_gate, "_lint_score", return_value=(None, [])):
            self.assertEqual(self._run(turn), "")

    def test_block_absorbs_warns_rather_than_emitting_both(self):
        # A block and a warn are different top-level contracts. When ui blocks,
        # the diff warning must be folded into the reason, not emitted beside it.
        turn = _turn(edits=["/app/a.tsx", "/docs/b.md"])
        data = json.loads(self._run(turn))
        self.assertEqual(data["decision"], "block")
        self.assertNotIn("hookSpecificOutput", data)
        self.assertIn("b.md", data["reason"])


if __name__ == "__main__":
    unittest.main()
