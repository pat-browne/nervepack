#!/usr/bin/env python3
"""The scheduled-auth token fallback in np_model's backend env.

The `claude` CLI's own interactive credentials expire independently of the
long-lived token nervepack mints with `claude setup-token`. Before this
fallback, only the scheduler installers injected that token (via
np_token_lib.claude_token_env_prefix, a shell snippet prepended to each cron
job), so a machine with a valid token file still failed every NON-cron model
call -- doctor's `llm-cli` check, episodic capture, the evaluator, recall --
with "OAuth session expired and could not be refreshed" while
`scheduled-auth-token` reported PASS. np_model is the sole model seam, so the
fallback belongs here rather than in each caller.

Same host-agnostic harness as test_np_model_contract.py: np_bashlib.argv is
monkeypatched to identity and run_killtree to a recorder, so the env np_model
built is captured without executing anything. Stdlib unittest, per CLAUDE.md.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "nervepack_engine")))

import np_model  # noqa: E402

# Deliberately NOT shaped like a real credential: the engine tree is scanned by
# publish/np-publish-scan.py, and a realistic-looking literal here would trip the
# pii-guard CI job (or need a SKIP_FILES entry). The fallback does not parse the
# token, so its shape is irrelevant to what these tests pin.
_TOKEN = "np-test-token-value"


class _Rec:
    def __init__(self, stdout="OUT", stderr="ERR", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TokenFallback(unittest.TestCase):
    def setUp(self):
        self.captured = {}
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self._own_dir = os.path.join(self._tmp, "own")
        os.makedirs(self._own_dir)
        self._token_file = os.path.join(self._tmp, "claude-oauth-token")

        def _fake_run(argv, input=None, env=None, cwd=None, timeout=None):
            self.captured = {"argv": argv, "env": env}
            return _Rec()

        for name, side in (("argv", lambda a: a), ("run_killtree", _fake_run)):
            p = mock.patch.object(np_model.np_bashlib, name, side_effect=side)
            p.start()
            self.addCleanup(p.stop)

    def _write_token(self, text=_TOKEN):
        with open(self._token_file, "w") as fh:
            fh.write(text)

    def _env(self, **extra):
        e = {
            "CLAUDE_BIN": "/fake/claude",
            "NP_OWN_SESSIONS_DIR": self._own_dir,
            "NP_CLAUDE_TOKEN_FILE": self._token_file,
        }
        e.update(extra)
        return mock.patch.dict(os.environ, e, clear=True)

    def _token_in_env(self):
        return self.captured["env"].get("CLAUDE_CODE_OAUTH_TOKEN")

    # ----- the fallback fires -----
    def test_complete_injects_token_when_absent(self):
        self._write_token()
        with self._env():
            np_model.complete("ping")
        self.assertEqual(self._token_in_env(), _TOKEN)

    def test_agent_injects_token_when_absent(self):
        self._write_token()
        with self._env():
            np_model.agent("task", "Bash")
        self.assertEqual(self._token_in_env(), _TOKEN)

    def test_trailing_newline_stripped(self):
        """The file is written by `claude setup-token > file`, so it ends in \\n.
        A token carrying the newline authenticates as garbage."""
        self._write_token(_TOKEN + "\n")
        with self._env():
            np_model.complete("ping")
        self.assertEqual(self._token_in_env(), _TOKEN)

    # ----- the fallback stays out of the way -----
    def test_existing_env_token_wins(self):
        """An explicitly exported token (what the cron prefix already does) must
        not be clobbered by the file -- the caller's env is the authority."""
        self._write_token()
        with self._env(CLAUDE_CODE_OAUTH_TOKEN="from-caller"):
            np_model.complete("ping")
        self.assertEqual(self._token_in_env(), "from-caller")

    def test_missing_token_file_is_not_an_error(self):
        with self._env():                       # no token file written
            np_model.complete("ping")
        self.assertIsNone(self._token_in_env())

    def test_empty_token_file_is_not_injected(self):
        self._write_token("\n")
        with self._env():
            np_model.complete("ping")
        self.assertIsNone(self._token_in_env())

    def test_unreadable_token_file_fails_open(self):
        """A directory at the token path makes the read raise IsADirectoryError.
        The seam must degrade to no-token, not take down every model call."""
        os.makedirs(self._token_file)
        with self._env():
            np_model.complete("ping")
        self.assertIsNone(self._token_in_env())

    def test_local_backend_does_not_receive_the_token(self):
        """NP_LLM_AGENT_CMD / np-llm-local.py talk to a non-Anthropic endpoint.
        Handing them a Claude OAuth token leaks a credential to a process that
        has no use for it."""
        self._write_token()
        with self._env(NP_LLM_BACKEND="local"):
            np_model.complete("ping")
        self.assertIsNone(self._token_in_env())


if __name__ == "__main__":
    unittest.main()
