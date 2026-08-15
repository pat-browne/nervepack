# np-test: implement-sigchld-reset | the implement job's own subprocess tree
#          must get normal wait() semantics, not inherit the server's SIG_IGN.
"""Root cause of a live CI-only failure (GitHub Actions Ubuntu runner,
2026-08-15): np-dashboard-server.py's _autoreap_children() sets this process's
SIGCHLD to SIG_IGN so its own detached implement jobs never zombie
(np-dashboard-server.py's own docstring on that function). But
subprocess.Popen's restore_signals (default True) only resets SIGPIPE/SIGXFSZ/
SIGXFZ before exec -- NOT SIGCHLD -- so SIG_IGN survives exec() and is
inherited by the entire descendant tree: the spawned `cli.py
implement-suggestion` process, and every git/agent subprocess IT spawns.

On Linux, SIG_IGN for SIGCHLD makes the KERNEL auto-reap children immediately.
That races any explicit waitpid() in that whole subtree: git's own internal
helper-process reap (surfacing as git's own "waitpid for branch failed: No
child processes" stderr) AND Python's subprocess.communicate() in
np_implement_suggestion.py, which can then report returncode=0 for a git
command that never actually ran -- observed live as `git worktree add`
reporting success while never creating the worktree, cascading into
np_implement_suggestion.py reading a real commit that was never made.
(Root-caused via test_implement_worktree_verify.py's phantom-success guard,
which stops that symptom; this test guards the actual mechanism.)

macOS does not reproduce this timing (auto-reap-on-SIG_IGN behaves
differently there), so this can only be verified by asserting the FIX
mechanism itself -- the preexec_fn resets SIGCHLD to SIG_DFL in the child --
portably on any POSIX host, not by reproducing the Linux-only kernel race.
"""
import os
import signal
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)

import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location(
    "np_dashboard_server", os.path.join(SETUP, "np-dashboard-server.py"))
_dashboard_server = importlib.util.module_from_spec(_spec)


@unittest.skipIf(os.name == "nt", "SIGCHLD does not exist on Windows")
class TestImplementSigchldReset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _spec.loader.exec_module(_dashboard_server)

    def test_preexec_resets_sigchld_to_default_in_the_child(self):
        """Simulates the exact inherited state: THIS process (standing in for
        the server, which already called _autoreap_children()) has SIGCHLD
        ignored. A child spawned with the module's implement-job preexec_fn
        must see SIG_DFL, not the inherited SIG_IGN -- otherwise every
        subprocess call inside that child's own process tree (git, the agent)
        races the kernel's auto-reap and can misreport its exit status."""
        # Print the raw int value, not signal.getsignal()'s return object --
        # some Python versions/platforms return a bare int for SIG_DFL/SIG_IGN,
        # others a Handlers enum member whose str()/repr() differs across
        # versions; comparing ints is the only version-portable check.
        old = signal.getsignal(signal.SIGCHLD)
        signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        try:
            r = subprocess.run(
                [sys.executable, "-c",
                 "import signal; print(int(signal.getsignal(signal.SIGCHLD)))"],
                capture_output=True, text=True,
                preexec_fn=_dashboard_server.implement_job_preexec)
        finally:
            signal.signal(signal.SIGCHLD, old)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(int(r.stdout.strip()), int(signal.SIG_DFL))


if __name__ == "__main__":
    unittest.main()
