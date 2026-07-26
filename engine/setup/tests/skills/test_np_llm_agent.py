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


if __name__ == "__main__":
    unittest.main()
