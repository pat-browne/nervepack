"""Tests for np_llm_agent.py -- the shared subprocess seam for np-llm.sh's
`agent` mode, used by every ported agentic cron (skill-maintain's Sonnet pass
in Phase 10, and the future 71/72/76/77 ports). Stubs np-llm.sh itself (via a
CLAUDE_BIN-shaped stub is NOT needed here -- we stub np-llm.sh directly, one
layer up, since this seam's own contract is "did we correctly invoke np-llm.sh
agent with the right prompt/tools/cwd", not "did claude itself behave"."""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_llm_agent  # noqa: E402


def _write_stub_np_llm(path, behavior):
    """A fake np-llm.sh that records its invocation (argv + stdin + cwd) to a
    sentinel file next to itself, then behaves per `behavior` ('success' exits 0
    after touching a marker in cwd; 'fail' exits 1)."""
    script = """#!/usr/bin/env bash
{ echo "ARGS:$@"; cat; echo; echo "CWD:$(pwd)"; } > "%s/invocation.log"
""" % os.path.dirname(path)
    if behavior == "success":
        script += 'touch "$(pwd)/agent-ran-here"\nexit 0\n'
    else:
        script += 'exit 1\n'
    with open(path, "w") as fh:
        fh.write(script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class TestRunAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.stub = os.path.join(self.tmp, "np-llm.sh")
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _patch_np_llm_path(self):
        return mock.patch.object(np_llm_agent, "_NP_LLM_PATH", self.stub)

    def test_1_success_returns_true_and_invokes_correctly(self):
        _write_stub_np_llm(self.stub, "success")
        target = os.path.join(self.tmp, "target_repo")
        os.makedirs(target)
        with self._patch_np_llm_path():
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd=target)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(os.path.join(target, "agent-ran-here")),
                         "agent subprocess did not run with the requested cwd")
        with open(os.path.join(self.tmp, "invocation.log")) as fh:
            log = fh.read()
        self.assertIn("ARGS:agent --tools Read Write Edit", log)
        self.assertIn("do the thing", log)
        self.assertIn("CWD:%s" % os.path.realpath(target), log)

    def test_2_failure_returns_false(self):
        _write_stub_np_llm(self.stub, "fail")
        with self._patch_np_llm_path():
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd=self.tmp)
        self.assertFalse(ok)

    def test_3_missing_np_llm_fails_open_returns_false(self):
        with self._patch_np_llm_path():
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd=self.tmp)
        self.assertFalse(ok)

    def test_4_cwd_none_defaults_to_current_directory(self):
        _write_stub_np_llm(self.stub, "success")
        cwd_before = os.getcwd()
        with self._patch_np_llm_path():
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd=None)
        self.assertTrue(ok)
        with open(os.path.join(self.tmp, "invocation.log")) as fh:
            log = fh.read()
        self.assertIn("CWD:%s" % os.path.realpath(cwd_before), log)


if __name__ == "__main__":
    unittest.main()
