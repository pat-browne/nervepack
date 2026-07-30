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
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestSessionFlush(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "session-flush.log")
        # Per-test stamp/lock so the throttle and the single-flush lock are
        # hermetic -- otherwise every test after the first would be throttled by
        # the previous one's stamp in the real cache dir.
        self.stamp = os.path.join(self.tmp, "last-flush")
        self.lock = os.path.join(self.tmp, "session-flush.lock")
        self._env = mock.patch.dict(os.environ, {
            "SESSION_FLUSH_LOG": self.log,
            "SESSION_FLUSH_STAMP": self.stamp,
            "SESSION_FLUSH_LOCK": self.lock,
        }, clear=False)
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
        # Every real substep is a .py entrypoint run via sys.executable (session_flush
        # has no bash branch), so the detach-proof stubs are Python too.
        stub1 = os.path.join(self.tmp, "stub1.py")
        stub2 = os.path.join(self.tmp, "stub2.py")
        with open(stub1, "w") as fh:
            fh.write("import time\ntime.sleep(1)\nopen(%r, 'w').close()\n" % marker1)
        with open(stub2, "w") as fh:
            fh.write("import time\ntime.sleep(1)\nopen(%r, 'w').close()\n" % marker2)

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


class TestSessionFlushThrottleAndLock(TestSessionFlush):
    """#202 bug 4: session_flush ran on EVERY SessionEnd with no interval and no
    lock -- ~640 flushes in one day, occasionally 3 concurrent, all writing to
    one shared git working tree."""

    def setUp(self):
        super().setUp()
        self.conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.conf, "w") as fh:
            fh.write("memory|shared|runtime|on|flush_interval=900\n")
        p = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local"),
        }, clear=False)
        p.start()
        self.addCleanup(p.stop)

    def test_5_second_flush_inside_the_interval_is_skipped(self):
        ran = []
        with mock.patch.dict(os.environ, {"NP_FLUSH_NODETACH": "1"}):
            self._run(step_fns=[lambda: ran.append("a")])
            self.assertEqual(ran, ["a"])
            self._run(step_fns=[lambda: ran.append("b")])
        self.assertEqual(ran, ["a"], "a flush inside the interval must not do work")

    def test_6_flush_runs_again_once_the_interval_has_passed(self):
        ran = []
        with mock.patch.dict(os.environ, {"NP_FLUSH_NODETACH": "1"}):
            self._run(step_fns=[lambda: ran.append("a")])
            old = int(time.time()) - 901
            with open(self.stamp, "w") as fh:
                fh.write(str(old))
            self._run(step_fns=[lambda: ran.append("b")])
        self.assertEqual(ran, ["a", "b"])

    def test_7_throttle_short_circuits_before_spawning_a_detached_child(self):
        """The cheap win: don't even fork when we know the work will be skipped."""
        from nervepack_engine.hooks import session_flush
        with open(self.stamp, "w") as fh:
            fh.write(str(int(time.time())))
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(session_flush.subprocess, "Popen") as popen:
            os.environ.pop("NP_FLUSH_NODETACH", None)
            session_flush.run("")
            popen.assert_not_called()

    def test_8_a_live_lock_holder_blocks_a_concurrent_flush(self):
        ran = []
        os.makedirs(os.path.dirname(self.lock), exist_ok=True)
        with open(self.lock, "w") as fh:
            fh.write(str(os.getpid()))          # this test process: definitely alive
        with mock.patch.dict(os.environ, {"NP_FLUSH_NODETACH": "1"}):
            self._run(step_fns=[lambda: ran.append("a")])
        self.assertEqual(ran, [], "a second concurrent flush must not run the substeps")

    def test_9_lock_is_released_so_the_next_flush_can_run(self):
        ran = []
        with mock.patch.dict(os.environ, {"NP_FLUSH_NODETACH": "1"}):
            self._run(step_fns=[lambda: ran.append("a")])
        self.assertFalse(os.path.exists(self.lock), "lock leaked after a completed flush")

    def test_10_lock_is_released_even_when_a_substep_raises(self):
        def _boom():
            raise RuntimeError("boom")
        with mock.patch.dict(os.environ, {"NP_FLUSH_NODETACH": "1"}):
            self._run(step_fns=[_boom])
        self.assertFalse(os.path.exists(self.lock), "lock leaked after a failing substep")

    def test_11_stale_lock_from_a_dead_pid_is_reclaimed(self):
        ran = []
        with open(self.lock, "w") as fh:
            fh.write("999999999")               # not a live pid
        with mock.patch.dict(os.environ, {"NP_FLUSH_NODETACH": "1"}):
            self._run(step_fns=[lambda: ran.append("a")])
        self.assertEqual(ran, ["a"], "a crashed holder's lock must not wedge flushing forever")


if __name__ == "__main__":
    unittest.main()
