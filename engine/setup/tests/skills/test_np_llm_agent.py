"""Tests for np_llm_agent.py -- the shared seam for the backend-neutral
agentic-call contract every ported maintenance cron needs. As of phase 9 of
the bash->Python CLI consolidation, run_agent() calls np_model.agent()
in-process (no more shelling to bash np-llm.sh) -- these tests verify the
seam's own contract ("did we correctly forward prompt/tools/cwd and translate
the exit code to True/False"), mocking np_model.agent directly rather than
stubbing a subprocess.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "nervepack_engine")))  # phase 20b-2: relocated library modules

import np_llm_agent  # noqa: E402


class TestRunAgent(unittest.TestCase):
    def test_1_success_returns_true_and_forwards_args(self):
        calls = []

        def fake_agent(prompt, tools, cwd=None, timeout=None):
            calls.append((prompt, tools, cwd))
            return (0, "", "")

        with mock.patch.object(np_llm_agent.np_model, "agent", side_effect=fake_agent):
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd="/some/repo")
        self.assertTrue(ok)
        self.assertEqual(calls, [("do the thing", "Read Write Edit", "/some/repo")])

    def test_2_nonzero_exit_returns_false(self):
        with mock.patch.object(np_llm_agent.np_model, "agent", return_value=(1, "", "boom")):
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd="/tmp")
        self.assertFalse(ok)

    def test_3_value_error_fails_open_returns_false(self):
        # e.g. an unimplemented NP_LLM_BACKEND, which np_model.agent() raises on
        with mock.patch.object(np_llm_agent.np_model, "agent", side_effect=ValueError("bad backend")):
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd="/tmp")
        self.assertFalse(ok)

    def test_4_cwd_none_forwarded_as_none(self):
        calls = []

        def fake_agent(prompt, tools, cwd=None, timeout=None):
            calls.append(cwd)
            return (0, "", "")

        with mock.patch.object(np_llm_agent.np_model, "agent", side_effect=fake_agent):
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd=None)
        self.assertTrue(ok)
        self.assertEqual(calls, [None])

    def test_5_oserror_fails_open_returns_false(self):
        with mock.patch.object(np_llm_agent.np_model, "agent",
                                side_effect=OSError("simulated exec failure")):
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd="/tmp")
        self.assertFalse(ok)

    def test_6_timeout_forwarded_to_agent(self):
        # #173: the maintenance seam must be able to bound the agent call so a hung
        # headless stream can't wedge the cron. Forward the timeout to np_model.agent.
        got = {}

        def fake_agent(prompt, tools, cwd=None, timeout=None):
            got["timeout"] = timeout
            return (0, "", "")

        with mock.patch.object(np_llm_agent.np_model, "agent", side_effect=fake_agent):
            np_llm_agent.run_agent("p", "Read", cwd="/tmp", timeout=42)
        self.assertEqual(got["timeout"], 42)


class TestRunAgentLogPath(unittest.TestCase):
    """The retired bash cron bodies ended `... | np-llm.sh agent ... >> "$LOG" 2>&1`,
    so the maintenance agent's own report landed in the cron log. The phase-9 port
    dropped stdout/stderr on the floor, leaving every run as a bare
    `=== <name> run ===` header -- healthy runs and failures became
    indistinguishable. `log_path` restores the bash behaviour."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "sub", "cron.log")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read(self):
        with open(self.log, encoding="utf-8") as fh:
            return fh.read()

    def test_7_stdout_and_stderr_appended_to_log_path(self):
        with mock.patch.object(np_llm_agent.np_model, "agent",
                                return_value=(0, "the report body\n", "a warning\n")):
            ok = np_llm_agent.run_agent("p", "Read", cwd="/tmp", log_path=self.log)
        self.assertTrue(ok)
        body = self._read()
        self.assertIn("the report body", body)
        self.assertIn("a warning", body)

    def test_8_appends_rather_than_truncates(self):
        os.makedirs(os.path.dirname(self.log), exist_ok=True)
        with open(self.log, "w", encoding="utf-8") as fh:
            fh.write("=== earlier run ===\n")
        with mock.patch.object(np_llm_agent.np_model, "agent",
                                return_value=(0, "second report\n", "")):
            np_llm_agent.run_agent("p", "Read", cwd="/tmp", log_path=self.log)
        body = self._read()
        self.assertIn("=== earlier run ===", body)
        self.assertIn("second report", body)

    def test_9_failure_output_still_logged(self):
        # The diagnostic that matters most: a failing agent's stderr must survive.
        with mock.patch.object(np_llm_agent.np_model, "agent",
                                return_value=(1, "", "Failed to authenticate: OAuth session expired\n")):
            ok = np_llm_agent.run_agent("p", "Read", cwd="/tmp", log_path=self.log)
        self.assertFalse(ok)
        self.assertIn("OAuth session expired", self._read())

    def test_10_no_log_path_is_backward_compatible(self):
        with mock.patch.object(np_llm_agent.np_model, "agent",
                                return_value=(0, "out", "err")):
            ok = np_llm_agent.run_agent("p", "Read", cwd="/tmp")
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.log))

    def test_11_unwritable_log_path_fails_open(self):
        # invariant 1: logging must never break the cron.
        with mock.patch.object(np_llm_agent.np_model, "agent",
                                return_value=(0, "out", "")):
            ok = np_llm_agent.run_agent("p", "Read", cwd="/tmp",
                                        log_path=os.path.join(os.sep, "proc", "nope", "x.log"))
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
