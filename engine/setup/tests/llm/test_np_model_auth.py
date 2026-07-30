#!/usr/bin/env python3
"""Auth-failure detection at the model seam (#201).

The `claude` CLI prints `Failed to authenticate: OAuth session expired and could
not be refreshed` to **stdout and exits 0**, so every caller downstream saw a
well-formed-looking response that merely failed to be JSON. Capture and the
evaluator bailed with a generic "returned non-JSON output" and burned their
whole retry budget on a condition no retry can fix; dashboard Implement read it
as the benign "agent produced no commit" (#211).

These tests pin that the seam raises a typed np_model.AuthError instead of
returning the bogus text -- and, just as importantly, that a *legitimate* model
response merely discussing auth failure does NOT trip the detector. Capture
summarizes session transcripts, so a session about this very bug is a real
false-positive risk; detection is anchored to the first line of output, which is
the whole of what the CLI emits on an auth failure.

Same monkeypatch approach as test_np_model_contract.py (run_killtree -> recorder,
nothing is executed). Stdlib unittest, per CLAUDE.md.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "nervepack_engine")))

import np_model  # noqa: E402


class _Rec:
    def __init__(self, stdout="OUT", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# Verbatim from the confirmed repro in #201 (note the trailing space the CLI emits).
_OAUTH_EXPIRED = "Failed to authenticate: OAuth session expired and could not be refreshed \n"
# The other observed form, from the stale-CLAUDE_CODE_SESSION_ID incident.
_NOT_LOGGED_IN = "Not logged in · Please run /login\n"


class AuthDetection(unittest.TestCase):
    def setUp(self):
        self.stdout = "OUT"
        self.returncode = 0

        def _fake_run(argv, input=None, env=None, cwd=None, timeout=None):
            return _Rec(stdout=self.stdout, returncode=self.returncode)

        p_argv = mock.patch.object(np_model.np_bashlib, "argv", side_effect=lambda a: a)
        p_run = mock.patch.object(np_model.np_bashlib, "run_killtree", side_effect=_fake_run)
        p_argv.start()
        p_run.start()
        self.addCleanup(p_argv.stop)
        self.addCleanup(p_run.stop)
        p_env = mock.patch.dict(os.environ, {"CLAUDE_BIN": "/fake/claude"}, clear=False)
        p_env.start()
        self.addCleanup(p_env.stop)

    # --- complete() ---------------------------------------------------------

    def test_complete_raises_on_oauth_expired(self):
        self.stdout = _OAUTH_EXPIRED
        with self.assertRaises(np_model.AuthError) as cm:
            np_model.complete("hi")
        self.assertIn("OAuth session expired", str(cm.exception))

    def test_complete_raises_on_not_logged_in(self):
        self.stdout = _NOT_LOGGED_IN
        with self.assertRaises(np_model.AuthError):
            np_model.complete("hi")

    def test_complete_passes_through_normal_output(self):
        self.stdout = '{"summary": "did a thing"}\n'
        self.assertEqual(np_model.complete("hi"), '{"summary": "did a thing"}\n')

    def test_complete_does_not_trip_on_discussion_of_auth_failure(self):
        """A capture summary of a session ABOUT this bug quotes the error text.
        Anchoring to the first line keeps that a normal response, not an AuthError."""
        self.stdout = (
            '{"topic": "nervepack auth bug", "summary": "Root-caused #201: the CLI '
            'prints Failed to authenticate: OAuth session expired and could not be '
            'refreshed to stdout and exits 0."}\n')
        out = np_model.complete("hi")
        self.assertIn("Root-caused #201", out)

    # --- agent() ------------------------------------------------------------

    def test_agent_raises_on_oauth_expired(self):
        self.stdout = _OAUTH_EXPIRED
        with self.assertRaises(np_model.AuthError):
            np_model.agent("task", "Bash Read")

    def test_agent_passes_through_normal_output(self):
        self.stdout = "made the edit and committed\n"
        rc, out, err = np_model.agent("task", "Bash Read")
        self.assertEqual(rc, 0)
        self.assertIn("made the edit", out)

    def test_auth_error_is_not_confusable_with_a_benign_result(self):
        """#211: fail-open callers catch broad Exception. AuthError must still be
        distinguishable from a generic failure, so it is its own type."""
        self.assertTrue(issubclass(np_model.AuthError, Exception))
        self.assertIsNot(np_model.AuthError, Exception)


if __name__ == "__main__":
    unittest.main()
