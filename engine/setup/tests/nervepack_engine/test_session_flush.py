"""Tests for nervepack_engine.hooks.session_flush -- the Python port of
np-session-flush.sh. Process detachment uses subprocess.Popen(start_new_session=
True) -- a single cross-platform path (see this phase's plan for why the bash
original's Linux-setsid-vs-macOS-nohup+disown branch collapses to one code path
in Python). Ports test_session_flush.sh's 3 scenarios: guard [covered
generically by test_cli.py -- NOT re-tested here], foreground-both-substeps,
and a REAL (unmocked) detach-and-complete proof mirroring the bash test's own
technique (stub substeps that sleep then touch a marker file)."""
import os
import sys
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestSessionFlush(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "session-flush.log")
        self._env = mock.patch.dict(os.environ, {"SESSION_FLUSH_LOG": self.log}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("NP_FLUSH_DETACHED", None)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, **kwargs):
        from nervepack_engine.hooks import session_flush
        return session_flush.run("", **kwargs)

    def _log_text(self):
        try:
            with open(self.log, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    def test_1_foreground_runs_both_substeps_in_order(self):
        order = []
        with mock.patch.dict(os.environ, {"NP_FLUSH_NODETACH": "1"}):
            out = self._run(step_fns=[lambda: order.append("metrics"), lambda: order.append("episodic")])
        self.assertEqual(out, "")
        self.assertEqual(order, ["metrics", "episodic"])
        self.assertIn("flush start", self._log_text())
        self.assertIn("flush done", self._log_text())

    def test_2_foreground_a_failing_substep_does_not_block_the_next(self):
        order = []
        def _boom():
            raise RuntimeError("boom")
        with mock.patch.dict(os.environ, {"NP_FLUSH_NODETACH": "1"}):
            self._run(step_fns=[_boom, lambda: order.append("episodic")])
        self.assertEqual(order, ["episodic"])
        self.assertIn("flush done", self._log_text())

    def test_3_detach_spawns_and_returns_immediately_mocked(self):
        from nervepack_engine.hooks import session_flush
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(session_flush.subprocess, "Popen") as popen:
            os.environ.pop("NP_FLUSH_NODETACH", None)
            out = session_flush.run("")
            popen.assert_called_once()
            _args, kwargs = popen.call_args
            self.assertTrue(kwargs.get("start_new_session"))
            self.assertEqual(kwargs.get("env", {}).get("NP_FLUSH_DETACHED"), "1")
        self.assertEqual(out, "")
        self.assertNotIn("flush start", self._log_text())

    def test_4_real_unmocked_detach_returns_fast_and_completes_async(self):
        # Mirrors test_session_flush.sh's own detach proof: stub substeps that
        # sleep then touch a marker, proving the outer call truly backgrounds
        # rather than running the substeps synchronously.
        marker1 = os.path.join(self.tmp, "step1.done")
        marker2 = os.path.join(self.tmp, "step2.done")
        stub1 = os.path.join(self.tmp, "stub1.sh")
        stub2 = os.path.join(self.tmp, "stub2.sh")
        with open(stub1, "w") as fh:
            fh.write("#!/usr/bin/env bash\nsleep 1\ntouch '%s'\n" % marker1)
        with open(stub2, "w") as fh:
            fh.write("#!/usr/bin/env bash\nsleep 1\ntouch '%s'\n" % marker2)
        os.chmod(stub1, 0o755)
        os.chmod(stub2, 0o755)

        from nervepack_engine.hooks import session_flush
        with mock.patch.object(session_flush, "_STEP_PATHS", [stub1, stub2]):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NP_FLUSH_NODETACH", None)
                started = time.time()
                out = session_flush.run("")
                elapsed = time.time() - started
        self.assertEqual(out, "")
        self.assertLess(elapsed, 2.0, "run() did not return promptly -- detach failed")
        self.assertFalse(os.path.isfile(marker1), "substep ran synchronously instead of detaching")

        for _ in range(30):
            if os.path.isfile(marker1) and os.path.isfile(marker2):
                break
            time.sleep(0.2)
        self.assertTrue(os.path.isfile(marker1), "detached substep 1 never completed")
        self.assertTrue(os.path.isfile(marker2), "detached substep 2 never completed")


if __name__ == "__main__":
    unittest.main()
