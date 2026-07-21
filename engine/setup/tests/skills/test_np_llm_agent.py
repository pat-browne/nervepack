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
        # The isfile check is the real cross-platform proof of correct cwd (a
        # real file landed exactly where Python's own path resolution expects).
        # We deliberately do NOT string-match the stub's self-reported
        # "CWD:$(pwd)" against os.path.realpath(target): on Windows, bash
        # reports its cwd in MSYS/mount-aliased form (e.g. "/tmp/...", not
        # "C:\Users\...\Temp\..."), so the two can never match even when the
        # subprocess ran in the exact right directory.
        self.assertTrue(os.path.isfile(os.path.join(target, "agent-ran-here")),
                         "agent subprocess did not run with the requested cwd")
        with open(os.path.join(self.tmp, "invocation.log")) as fh:
            log = fh.read()
        self.assertIn("ARGS:agent --tools Read Write Edit", log)
        self.assertIn("do the thing", log)

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
        # cwd=None means the stub's "success" behavior (touch agent-ran-here)
        # lands in the REAL current directory -- clean it up unconditionally,
        # win or fail, so this test never leaks a stray file into the repo.
        marker = os.path.join(cwd_before, "agent-ran-here")
        self.addCleanup(lambda: os.remove(marker) if os.path.exists(marker) else None)
        with self._patch_np_llm_path():
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd=None)
        self.assertTrue(ok)
        # See test_1's comment: isfile is the robust cross-platform proof of
        # correct cwd, not a string-match against bash's self-reported pwd.
        self.assertTrue(os.path.isfile(marker),
                         "agent subprocess did not run in the caller's cwd")

    def test_5_subprocess_oserror_fails_open_returns_false(self):
        """Directly exercises the `except OSError:` branch by making
        subprocess.run itself raise, rather than relying on a subprocess
        that merely exits nonzero (that's test_2/test_3's job)."""
        with mock.patch.object(np_llm_agent.subprocess, "run",
                                side_effect=OSError("simulated exec failure")):
            ok = np_llm_agent.run_agent("do the thing", "Read Write Edit", cwd=self.tmp)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
