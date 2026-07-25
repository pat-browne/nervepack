#!/usr/bin/env python3
# np-test: sync | happy+failure
"""Hermetic coverage of np_sync.py's defensive engine sync across all five engine
cases (up-to-date clean/dirty, dirty+behind, ahead, fast-forward, diverged) plus
not-a-git and the disabled/dry-run/throttle early-outs, and the status-file write.
Replaces the retired A/B parity test (test_sync_parity.sh) now that
40-sync-nervepack.sh is gone. Drives `python3 np_sync.py` as a subprocess with a
temp NP_SYNC_TARGET / NP_SYNC_STATUS / NP_SYNC_STAMP and a temp toggles conf — never
touches the real repo."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_PY = os.path.join(_SETUP, "np_sync.py")


def _git(cwd, *args, **kw):
    env = dict(os.environ,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env, **kw)


@unittest.skipUnless(shutil.which("git"), "git required")
class NpSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".claude"))
        self.conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.conf, "w") as fh:
            fh.write("sync|shared|runtime|on|interval=86400\n")
        self.local = os.path.join(self.tmp, "toggles.local")
        open(self.local, "w").close()
        self.status = os.path.join(self.tmp, "status")
        self.stamp = os.path.join(self.tmp, "stamp")
        # A bare remote with one commit on main, cloned into `target`.
        self.remote = os.path.join(self.tmp, "remote.git")
        seed = os.path.join(self.tmp, "seed")
        _git(self.tmp, "init", "-q", "--bare", "-b", "main", self.remote)
        subprocess.run(["git", "init", "-q", "-b", "main", seed], capture_output=True)
        _git(seed, "commit", "-q", "--allow-empty", "-m", "c1")
        _git(seed, "remote", "add", "origin", self.remote)
        _git(seed, "push", "-q", "origin", "main")
        self.seed = seed
        self.target = os.path.join(self.tmp, "target")
        subprocess.run(["git", "clone", "-q", self.remote, self.target], capture_output=True)

    def _advance_remote(self, msg="c2"):
        _git(self.seed, "commit", "-q", "--allow-empty", "-m", msg)
        _git(self.seed, "push", "-q", "origin", "main")

    def _run(self, *args, dryrun=False, sync_off=False, fresh_stamp=False):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["NP_TOGGLES_CONF"] = self.conf
        env["NP_TOGGLES_LOCAL"] = self.local
        env["NP_SYNC_TARGET"] = self.target
        env["NP_SYNC_STATUS"] = self.status
        env["NP_SYNC_STAMP"] = self.stamp
        env["CLAUDE_SETTINGS"] = os.path.join(self.home, ".claude", "settings.json")
        env.pop("NP_SYNC_DRYRUN", None)
        env.pop("NP_TEAM_DIR", None)
        if dryrun:
            env["NP_SYNC_DRYRUN"] = "1"
        if sync_off:
            with open(self.local, "w") as fh:
                fh.write("sync=off\n")
        if fresh_stamp:
            with open(self.stamp, "w") as fh:
                fh.write(str(int(time.time())))
        r = subprocess.run([sys.executable, _PY, *args], capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def test_up_to_date_clean(self):
        out = self._run("exit")
        self.assertIn("up to date (", out)
        with open(self.status) as fh:
            self.assertIn("up to date (", fh.read())

    def test_up_to_date_dirty(self):
        with open(os.path.join(self.target, "dirty.txt"), "w") as fh:
            fh.write("x")
        out = self._run("exit")
        self.assertIn("up to date with origin", out)
        self.assertIn("uncommitted change", out)

    def test_fast_forward(self):
        self._advance_remote()
        out = self._run("exit")
        self.assertIn("fast-forwarded", out)
        self.assertIn("commit(s) to", out)
        # the ff actually moved local to origin/main
        self.assertEqual(_git(self.target, "rev-parse", "HEAD").stdout.strip(),
                         _git(self.target, "rev-parse", "origin/main").stdout.strip())

    def test_dirty_behind_skips(self):
        self._advance_remote()
        with open(os.path.join(self.target, "dirty.txt"), "w") as fh:
            fh.write("x")
        out = self._run("exit")
        self.assertIn("SKIPPED (working tree dirty", out)

    def test_ahead(self):
        _git(self.target, "commit", "-q", "--allow-empty", "-m", "local1")
        out = self._run("exit")
        self.assertIn("ahead of origin/main", out)

    def test_diverged(self):
        self._advance_remote()
        _git(self.target, "commit", "-q", "--allow-empty", "-m", "local1")
        out = self._run("exit")
        self.assertIn("DIVERGED", out)

    def test_not_a_git_repo(self):
        shutil.rmtree(os.path.join(self.target, ".git"))
        out = self._run("exit")
        self.assertIn("is not a git repo", out)

    def test_disabled_toggle(self):
        out = self._run("exit", sync_off=True)
        self.assertIn("disabled via toggle", out)

    def test_dryrun(self):
        out = self._run("exit", dryrun=True)
        self.assertIn("would sync now (mode=exit)", out)

    def test_backup_throttle(self):
        out = self._run("backup", fresh_stamp=True)
        self.assertIn("within", out)
        self.assertIn("skipping (backup)", out)


if __name__ == "__main__":
    unittest.main()
