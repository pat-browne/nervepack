#!/usr/bin/env python3
"""Backend argv/env contract for np_model.complete/agent -- the sole runtime model
seam since np-llm.sh was retired (phase 19). This is the in-process successor to the
old black-box `tests/llm/test_np_llm.sh`, which asserted the same contract against the
bash wrapper via a stub CLAUDE_BIN. It pins, for BOTH backends and BOTH modes, the
exact argv np_model builds, the NERVEPACK_AGENT=1 recursion guard, the CLAUDE_CODE_*
env strip, and that the prompt is passed on stdin.

Host-agnostic by construction: instead of stubbing an executable CLAUDE_BIN (a bash
shebang script native-Windows Python cannot CreateProcess -- the reason the old
parity tests were Windows-skipped), it monkeypatches np_bashlib.argv to identity and
np_bashlib.run_killtree to a recorder, capturing the argv/env/stdin np_model would
have executed WITHOUT running anything. Stdlib unittest (no pytest), per CLAUDE.md.
"""
import os
import sys
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "nervepack_engine")))  # phase 20b-2: relocated library modules

import np_model  # noqa: E402


class _Rec:
    """Stand-in for subprocess.CompletedProcess returned by run_killtree."""
    def __init__(self, stdout="OUT", stderr="ERR", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# Env vars np_model must strip from every backend call so a nested `claude`
# authenticates as its own top-level headless run (found 2026-07-13).
_STRIP = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID",
          "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_SSE_PORT")


class ModelContract(unittest.TestCase):
    def setUp(self):
        self.captured = {}
        import shutil
        import tempfile
        self._own_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._own_dir, True)

        def _fake_run(argv, input=None, env=None, cwd=None, timeout=None):
            self.captured = {"argv": argv, "input": input, "env": env, "cwd": cwd,
                             "timeout": timeout}
            return _Rec()

        # argv() -> identity so the captured argv is exactly what np_model built
        # (on Windows argv() may prepend an interpreter; identity keeps the
        # assertion host-agnostic). run_killtree -> recorder (never executes).
        self._p_argv = mock.patch.object(np_model.np_bashlib, "argv", side_effect=lambda a: a)
        self._p_run = mock.patch.object(np_model.np_bashlib, "run_killtree", side_effect=_fake_run)
        self._p_argv.start()
        self._p_run.start()
        self.addCleanup(self._p_argv.stop)
        self.addCleanup(self._p_run.stop)

        # A base env with the stale-session vars present, so the strip is a real
        # assertion (not vacuously satisfied by their absence).
        self._base = {
            "CLAUDE_BIN": "/fake/claude",
            "NP_LLM_MODEL_CHEAP": "cheapM",
            "NP_LLM_MODEL_AGENT": "agentM",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "stale-session",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "CLAUDE_CODE_CHILD_SESSION": "1",
        }

    def _env(self, **extra):
        e = dict(self._base)
        e.setdefault("NP_OWN_SESSIONS_DIR", self._own_dir)
        e.update(extra)
        return mock.patch.dict(os.environ, e, clear=True)

    def _split_session_id(self, argv):
        """Pull the `--session-id <uuid>` pair out of argv, asserting it is a real
        uuid, and return (argv_without_the_pair, sid). #202: nervepack mints the
        child's session id so the back-capture sweep can exclude its own
        `claude -p` transcripts instead of re-discovering them as new work."""
        self.assertIn("--session-id", argv, "np_model must name the child session")
        i = argv.index("--session-id")
        sid = argv[i + 1]
        uuid.UUID(sid)                       # raises if it isn't a well-formed uuid
        return argv[:i] + argv[i + 2:], sid

    def _assert_guard_and_strip(self):
        env = self.captured["env"]
        self.assertEqual(env.get("NERVEPACK_AGENT"), "1",
                         "np_model must set NERVEPACK_AGENT=1 on the backend call")
        for v in _STRIP:
            self.assertNotIn(v, env, "%s must be stripped from the backend env" % v)

    # ----- claude backend: complete -----
    def test_complete_claude_argv_guard_strip_stdin(self):
        with self._env():
            out = np_model.complete("hello")
        argv, sid = self._split_session_id(self.captured["argv"])
        self.assertTrue(os.path.exists(os.path.join(self._own_dir, sid)),
                        "the minted session id must be recorded as nervepack's own")
        self.assertEqual(argv,
                         ["/fake/claude", "-p", "--model", "cheapM", "--allowedTools", ""])
        self.assertEqual(self.captured["input"], "hello")   # prompt on stdin
        self.assertEqual(out, "OUT")                        # returns backend stdout
        self.assertNotIn("--bare", self.captured["argv"])   # --bare breaks keychain auth
        self._assert_guard_and_strip()

    def test_complete_claude_system_appended(self):
        with self._env():
            np_model.complete("p", system="SYSPROMPT")
        self.assertEqual(self.captured["argv"][-2:], ["--append-system-prompt", "SYSPROMPT"])

    # ----- claude backend: agent -----
    def test_agent_claude_argv_guard_strip_stdin(self):
        with self._env():
            rc, out, err = np_model.agent("task", "Bash Read Write")
        argv, sid = self._split_session_id(self.captured["argv"])
        self.assertTrue(os.path.exists(os.path.join(self._own_dir, sid)),
                        "the minted session id must be recorded as nervepack's own")
        self.assertEqual(argv, [
            "/fake/claude", "-p",
            "--settings", '{"hooks":{},"includeCoAuthoredBy":false}',
            "--permission-mode", "bypassPermissions",
            "--model", "agentM",
            "--allowedTools", "Bash", "Read", "Write",
        ])
        self.assertEqual(self.captured["input"], "task")
        self.assertEqual((rc, out, err), (0, "OUT", "ERR"))
        self.assertNotIn("--bare", self.captured["argv"])
        self._assert_guard_and_strip()

    # ----- local backend: complete -> np-llm-local.py -----
    def test_complete_local_argv(self):
        with self._env(NP_LLM_BACKEND="local"):
            np_model.complete("hi", system="S")
        argv = self.captured["argv"]
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("np-llm-local.py"), argv)
        self.assertEqual(argv[2:], ["complete", "--system", "S"])
        self.assertNotIn("--bare", argv)
        # --session-id is a claude-CLI flag; the local backend writes no Claude
        # transcript, so there is nothing for the sweep to exclude (#202).
        self.assertNotIn("--session-id", argv)
        self._assert_guard_and_strip()

    # ----- local backend: agent -> NP_LLM_AGENT_CMD via bash -c -----
    def test_agent_local_shells_agent_cmd_with_tools_env(self):
        with self._env(NP_LLM_BACKEND="local", NP_LLM_AGENT_CMD="run-goose"):
            np_model.agent("task", "Bash Read")
        self.assertEqual(self.captured["argv"], ["bash", "-c", "run-goose"])
        self.assertEqual(self.captured["env"].get("NP_LLM_TOOLS"), "Bash Read")
        self._assert_guard_and_strip()

    def test_agent_local_unset_cmd_errors_without_running(self):
        with self._env(NP_LLM_BACKEND="local"):
            rc, out, err = np_model.agent("task", "Bash")
        self.assertEqual(rc, 2)
        self.assertIn("NP_LLM_AGENT_CMD", err)
        self.assertEqual(self.captured, {})   # backend never invoked

    # ----- unknown backend fails loudly (both modes) -----
    def test_unknown_backend_raises(self):
        with self._env(NP_LLM_BACKEND="bogus"):
            with self.assertRaises(ValueError):
                np_model.complete("p")
        with self._env(NP_LLM_BACKEND="bogus"):
            with self.assertRaises(ValueError):
                np_model.agent("p", "Read")


if __name__ == "__main__":
    unittest.main()
