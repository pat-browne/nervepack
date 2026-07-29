# np-test: implement-lock-zombie | _pid_alive() must report a zombie as dead so
#          the self-healing lock actually self-heals.
"""A zombie (exited, not yet reaped) keeps its pid-table entry, so
`os.kill(pid, 0)` SUCCEEDS for it. That made _acquire_lock()'s self-heal a
no-op in the one case it exists for.

The reachable sequence, reproduced live 2026-07-29:
  1. np-dashboard-server.py Popen()s an implement job detached and drops the
     handle -- it never wait()s, so the child is never reaped.
  2. The job is killed (or crashes) before its own cleanup runs, leaving
     ~/.cache/nervepack/implement.lock with its pid inside.
  3. That pid is now a zombie parented to the still-running server, so
     os.kill(pid, 0) succeeds and _acquire_lock() concludes the owner is alive.
  4. Every later Implement click logs "busy: another implement is running"
     and silently does nothing, for as long as the server stays up.

Observed in the wild: implement.log carries that exact "busy" line twice on
2026-06-11.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "nervepack_engine"))
for p in (SETUP, ENGINE):
    if p not in sys.path:
        sys.path.insert(0, p)

import np_implement_suggestion as impl  # noqa: E402


@unittest.skipIf(os.name == "nt", "zombies are a POSIX process-model concept")
class ZombieLivenessTest(unittest.TestCase):
    def setUp(self):
        # A child that exits immediately and is deliberately NOT reaped, exactly
        # as np-dashboard-server.py leaves its detached implement jobs.
        self.proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
        deadline = time.time() + 10
        while time.time() < deadline:
            if self._state() == "Z":
                break
            time.sleep(0.05)

    def tearDown(self):
        try:
            self.proc.wait(timeout=5)   # reap it
        except Exception:
            pass

    def _state(self):
        try:
            with open("/proc/%d/stat" % self.proc.pid, encoding="utf-8") as fh:
                return fh.read().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return "?"

    def test_os_kill_still_succeeds_for_the_zombie(self):
        """Guards the premise: if this ever stops holding, the bug below is moot."""
        if self._state() != "Z":
            self.skipTest("could not produce a zombie on this platform")
        try:
            os.kill(self.proc.pid, 0)
        except ProcessLookupError:
            self.fail("expected os.kill to succeed for an unreaped zombie")

    def test_pid_alive_reports_zombie_as_dead(self):
        if self._state() != "Z":
            self.skipTest("could not produce a zombie on this platform")
        self.assertFalse(impl._pid_alive(self.proc.pid),
                         "a zombie has exited — treating it as alive wedges the "
                         "implement lock until the parent server restarts")

    def test_lock_is_reclaimed_from_a_zombie_owner(self):
        if self._state() != "Z":
            self.skipTest("could not produce a zombie on this platform")
        tmp = tempfile.mkdtemp()
        lock = os.path.join(tmp, "implement.lock")
        os.mkdir(lock)
        with open(os.path.join(lock, "pid"), "w", encoding="utf-8") as fh:
            fh.write(str(self.proc.pid))
        self.assertTrue(impl._acquire_lock(lock),
                        "a lock owned by a zombie must be reclaimable")

    def test_live_owner_still_holds_the_lock(self):
        # The guard must not over-correct into stealing a live owner's lock.
        live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            tmp = tempfile.mkdtemp()
            lock = os.path.join(tmp, "implement.lock")
            os.mkdir(lock)
            with open(os.path.join(lock, "pid"), "w", encoding="utf-8") as fh:
                fh.write(str(live.pid))
            self.assertTrue(impl._pid_alive(live.pid))
            self.assertFalse(impl._acquire_lock(lock))
        finally:
            live.kill()
            live.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
