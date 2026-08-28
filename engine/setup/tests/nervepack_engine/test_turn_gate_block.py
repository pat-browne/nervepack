"""Tests for turn_gate's blocking form mode and its SubagentStop lane (spec 0021).

A Stop hook fires AFTER the closing message reached the reader. Blocking cannot
un-send it, so the contract these tests pin is narrow and deliberate:

  - a block happens at most once per turn (stop_hook_active short circuits),
  - the reason forbids restating, so the continuation is a replacement rather
    than a second full answer,
  - every finding rides on one decision, so the model is never asked to fix one
    thing and then blocked again for another.

Preventing the bad first draft is the job of the form_directive hook, not this
one. See change-specs/feat-form-gate-enforcement.md.
"""
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

SLOP = ("It is important to note that we have successfully leveraged a robust "
        "and seamless approach; the comprehensive solution was utilized in "
        "order to facilitate the initiation of the process, and additionally "
        "the aforementioned changes were made by the system.")
CLEAN = "The parser reads the file. It writes one row per record."


def _fake_lint_score(text, timeout_s):
    """Stand in for the overlay linter, which the suite runner isolates away.

    These cases are about the DECISION the gate reaches, not about the linter's
    scoring, so a stub keeps them hermetic. It scores the two fixtures above and
    nothing else.
    """
    if not text.strip():
        return (None, [])
    if "leveraged" in text:
        return (20.0, [("banned", 9), ("semicolon", 1), ("passive", 2)])
    return (0.0, [])


def _turn(edits=(), delivery=(), final_text="", created=()):
    t = np_turn_parse.Turn()
    t.edits = list(edits)
    t.delivery = list(delivery)
    t.final_text = final_text
    t.created = list(created)
    return t


class TurnGateBlockTest(unittest.TestCase):
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

    def _run(self, turn, payload=None, **params):
        def fake_param(key, default=None):
            return params.get(key, default)

        with mock.patch.object(np_turn_parse, "parse", return_value=turn), \
             mock.patch.object(turn_gate.np_toggle, "enabled", return_value=True), \
             mock.patch.object(turn_gate, "_lint_score", side_effect=_fake_lint_score), \
             mock.patch.object(turn_gate.np_toggle, "param", side_effect=fake_param):
            return turn_gate.run(payload or self._payload())

    # --- blocking form mode ----------------------------------------------
    def test_form_block_returns_a_block_decision(self):
        out = self._run(_turn(final_text=SLOP), **{"turn_gate.form": "block",
                                                   "turn_gate.ui": "off",
                                                   "turn_gate.diff": "off"})
        data = json.loads(out)
        self.assertEqual(data.get("decision"), "block")

    def test_block_reason_forbids_restating(self):
        """The whole point of the mode. Without this instruction the model
        answers again in full and the reader sees the same content twice."""
        out = self._run(_turn(final_text=SLOP), **{"turn_gate.form": "block",
                                                   "turn_gate.ui": "off",
                                                   "turn_gate.diff": "off"})
        reason = json.loads(out).get("reason", "").lower()
        self.assertIn("do not restate", reason)
        self.assertIn("only the rewritten", reason)

    def test_form_warn_still_only_warns(self):
        out = self._run(_turn(final_text=SLOP), **{"turn_gate.form": "warn",
                                                   "turn_gate.ui": "off",
                                                   "turn_gate.diff": "off"})
        data = json.loads(out)
        self.assertIsNone(data.get("decision"))
        self.assertIn("hookSpecificOutput", data)

    def test_clean_text_never_blocks(self):
        out = self._run(_turn(final_text=CLEAN), **{"turn_gate.form": "block",
                                                    "turn_gate.ui": "off",
                                                    "turn_gate.diff": "off"})
        self.assertEqual(out, "")

    def test_stop_hook_active_short_circuits_before_blocking(self):
        """One block per turn, never a loop. This is the guard that keeps a
        blocking gate from being the thing that bricks a session."""
        payload = self._payload(stop_hook_active=True)
        out = self._run(_turn(final_text=SLOP), payload=payload,
                        **{"turn_gate.form": "block"})
        self.assertEqual(out, "")

    def test_ui_and_form_findings_ride_one_decision(self):
        """Two findings, one block. Blocking twice for one turn would produce
        exactly the duplicate output the mode exists to avoid."""
        out = self._run(_turn(edits=["/app/Button.tsx"], final_text=SLOP),
                        **{"turn_gate.form": "block", "turn_gate.ui": "block",
                           "turn_gate.diff": "off"})
        data = json.loads(out)
        self.assertEqual(data.get("decision"), "block")
        reason = data.get("reason", "")
        self.assertIn("Button.tsx", reason)
        self.assertIn("violations per 100 words", reason)

    def test_form_block_with_ui_warn_still_blocks(self):
        out = self._run(_turn(edits=["/app/Button.tsx"], final_text=SLOP),
                        **{"turn_gate.form": "block", "turn_gate.ui": "warn",
                           "turn_gate.diff": "off"})
        self.assertEqual(json.loads(out).get("decision"), "block")

    def test_form_off_ignores_slop(self):
        out = self._run(_turn(final_text=SLOP), **{"turn_gate.form": "off",
                                                   "turn_gate.ui": "off",
                                                   "turn_gate.diff": "off"})
        self.assertEqual(out, "")

    # --- SubagentStop lane -------------------------------------------------
    def test_subagent_stop_checks_form(self):
        payload = self._payload(hook_event_name="SubagentStop")
        out = self._run(_turn(final_text=SLOP), payload=payload,
                        **{"turn_gate.form": "block", "turn_gate.subagent": "on"})
        self.assertEqual(json.loads(out).get("decision"), "block")

    def test_subagent_stop_skips_the_delivery_checks(self):
        """A subagent shows nothing to a human, so 'you never showed the UI' is
        not a finding against it. Only the prose it hands back is."""
        payload = self._payload(hook_event_name="SubagentStop")
        out = self._run(_turn(edits=["/app/Button.tsx"], final_text=CLEAN),
                        payload=payload,
                        **{"turn_gate.ui": "block", "turn_gate.subagent": "on"})
        self.assertEqual(out, "")

    def test_subagent_lane_can_be_turned_off(self):
        payload = self._payload(hook_event_name="SubagentStop")
        out = self._run(_turn(final_text=SLOP), payload=payload,
                        **{"turn_gate.form": "block", "turn_gate.subagent": "off"})
        self.assertEqual(out, "")

    def test_main_stop_is_unaffected_by_the_subagent_toggle(self):
        out = self._run(_turn(final_text=SLOP),
                        **{"turn_gate.form": "block", "turn_gate.subagent": "off",
                           "turn_gate.ui": "off", "turn_gate.diff": "off"})
        self.assertEqual(json.loads(out).get("decision"), "block")


if __name__ == "__main__":
    unittest.main()
