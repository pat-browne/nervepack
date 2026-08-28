"""Tests for hooks.form_directive -- the preventive half of the form pair.

The hook has one job: put the output contract in front of the model before the
draft exists. What these tests pin is that it does that reliably and cheaply,
and that every failure path stays silent rather than breaking a turn.
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

from hooks import form_directive  # noqa: E402


class FormDirectiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        prior = os.environ.get("NP_FORM_DIRECTIVE_DIR")
        os.environ["NP_FORM_DIRECTIVE_DIR"] = os.path.join(self.tmp.name, "state")
        self.addCleanup(lambda: os.environ.__setitem__("NP_FORM_DIRECTIVE_DIR", prior)
                        if prior is not None
                        else os.environ.pop("NP_FORM_DIRECTIVE_DIR", None))

    def _run(self, sid="s1", enabled=True, content_root="", **params):
        def fake_param(key, default=None):
            return params.get(key, default)

        with mock.patch.object(form_directive.np_toggle, "enabled",
                               return_value=enabled), \
             mock.patch.object(form_directive.np_toggle, "param",
                               side_effect=fake_param), \
             mock.patch.object(form_directive.np_content, "content_dir",
                               return_value=content_root):
            return form_directive.run(json.dumps({"session_id": sid,
                                                  "prompt": "do a thing"}))

    def _context(self, out):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def test_injects_the_contract(self):
        ctx = self._context(self._run())
        self.assertIn("np-flow-concise-output", ctx)
        self.assertIn("no em dash", ctx)

    def test_output_shape_is_a_userpromptsubmit_context_block(self):
        data = json.loads(self._run())
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"],
                         "UserPromptSubmit")

    def test_toggle_off_is_silent(self):
        self.assertEqual(self._run(enabled=False), "")

    def test_turn_cadence_injects_every_turn(self):
        """The default. Prevention that fires once per session decays as the
        context grows, which is the failure that made advisory memory useless."""
        self.assertNotEqual(self._run(), "")
        self.assertNotEqual(self._run(), "")

    def test_session_cadence_injects_once(self):
        first = self._run(**{"form_directive.cadence": "session"})
        second = self._run(**{"form_directive.cadence": "session"})
        self.assertNotEqual(first, "")
        self.assertEqual(second, "")

    def test_session_cadence_is_per_session(self):
        self._run(sid="a", **{"form_directive.cadence": "session"})
        self.assertNotEqual(self._run(sid="b", **{"form_directive.cadence": "session"}), "")

    def test_overlay_file_replaces_the_default(self):
        root = self.tmp.name
        os.makedirs(os.path.join(root, "config"), exist_ok=True)
        with open(os.path.join(root, "config", "form-directive.txt"), "w") as fh:
            fh.write("my own contract")
        self.assertEqual(self._context(self._run(content_root=root)),
                         "my own contract")

    def test_empty_overlay_file_falls_back_to_the_default(self):
        root = self.tmp.name
        os.makedirs(os.path.join(root, "config"), exist_ok=True)
        with open(os.path.join(root, "config", "form-directive.txt"), "w") as fh:
            fh.write("   \n")
        self.assertIn("np-flow-concise-output", self._context(self._run(content_root=root)))

    def test_missing_overlay_file_falls_back_to_the_default(self):
        self.assertIn("np-flow-concise-output",
                      self._context(self._run(content_root=self.tmp.name)))

    def test_bad_payload_is_silent(self):
        with mock.patch.object(form_directive.np_toggle, "enabled", return_value=True):
            self.assertEqual(form_directive.run("not json"), "")
            self.assertEqual(form_directive.run("[1,2]"), "")

    def test_the_default_obeys_its_own_categorical_rules(self):
        """Self-application. A contract that breaks its own zero-tolerance rules
        teaches the opposite of what it says."""
        text = form_directive._DEFAULT
        prose = "\n".join(l for l in text.splitlines() if "not " not in l)
        self.assertNotIn("—", text)          # em dash
        self.assertNotIn(";", prose)
        self.assertNotIn("'s ", prose.replace("reader's", ""))


if __name__ == "__main__":
    unittest.main()
