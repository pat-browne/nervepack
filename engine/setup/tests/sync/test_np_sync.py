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
import stat
import subprocess
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_PY = os.path.normpath(os.path.join(_SETUP, "..", "nervepack_engine", "np_sync.py"))


def _rmtree(path):
    """Windows-safe recursive delete: git packs its object files read-only, so a
    plain shutil.rmtree raises PermissionError (WinError 5) on Windows. On an error,
    clear the read-only bit and retry. No-op difference off Windows."""
    def _fix(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    try:
        shutil.rmtree(path, onexc=_fix)          # Python 3.12+
    except TypeError:
        shutil.rmtree(path, onerror=_fix)        # Python < 3.12


def _git(cwd, *args, **kw):
    env = dict(os.environ,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env, **kw)


@unittest.skipUnless(shutil.which("git"), "git required")
class NpSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(_rmtree, self.tmp)
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

        # A second bare remote + clone, standing in for a configured personal
        # content overlay (e.g. ~/Code/nervepack-content) -- entirely separate
        # history from the engine's remote/target pair above.
        self.content_remote = os.path.join(self.tmp, "content-remote.git")
        content_seed = os.path.join(self.tmp, "content-seed")
        _git(self.tmp, "init", "-q", "--bare", "-b", "main", self.content_remote)
        subprocess.run(["git", "init", "-q", "-b", "main", content_seed], capture_output=True)
        _git(content_seed, "commit", "-q", "--allow-empty", "-m", "content-c1")
        _git(content_seed, "remote", "add", "origin", self.content_remote)
        _git(content_seed, "push", "-q", "origin", "main")
        self.content_seed = content_seed
        self.content_dir = os.path.join(self.tmp, "content")
        subprocess.run(["git", "clone", "-q", self.content_remote, self.content_dir],
                       capture_output=True)

    def _advance_remote(self, msg="c2"):
        _git(self.seed, "commit", "-q", "--allow-empty", "-m", msg)
        _git(self.seed, "push", "-q", "origin", "main")

    def _advance_content_remote(self, msg="content-c2"):
        _git(self.content_seed, "commit", "-q", "--allow-empty", "-m", msg)
        _git(self.content_seed, "push", "-q", "origin", "main")

    def _env(self, dryrun=False, sync_off=False, fresh_stamp=False, target=None,
              content_dir=None):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["NP_TOGGLES_CONF"] = self.conf
        env["NP_TOGGLES_LOCAL"] = self.local
        env["NP_SYNC_TARGET"] = target or self.target
        env["NP_SYNC_STATUS"] = self.status
        env["NP_SYNC_STAMP"] = self.stamp
        env["CLAUDE_SETTINGS"] = os.path.join(self.home, ".claude", "settings.json")
        env.pop("NP_SYNC_DRYRUN", None)
        env.pop("NP_TEAM_DIR", None)
        env.pop("NP_CONTENT_DIR", None)
        if dryrun:
            env["NP_SYNC_DRYRUN"] = "1"
        if sync_off:
            with open(self.local, "w") as fh:
                fh.write("sync=off\n")
        if fresh_stamp:
            with open(self.stamp, "w") as fh:
                fh.write(str(int(time.time())))
        if content_dir is not None:
            env["NP_CONTENT_DIR"] = content_dir
        return env

    def _run(self, *args, **kw):
        env = self._env(**kw)
        r = subprocess.run([sys.executable, _PY, *args], capture_output=True, text=True, env=env)
        return r.stdout.strip()

    def _run_full(self, *args, **kw):
        """Like _run, but returns (stdout, stderr) -- content-layer notes are
        stderr-only (mirrors _team_sync's existing non-fatal-note contract)."""
        env = self._env(**kw)
        r = subprocess.run([sys.executable, _PY, *args], capture_output=True, text=True, env=env)
        return r.stdout.strip(), r.stderr

    def test_up_to_date_clean(self):
        out = self._run("exit")
        self.assertIn("up to date (", out)
        with open(self.status) as fh:
            self.assertIn("up to date (", fh.read())

    def test_linked_worktree_is_recognized_as_a_repo(self):
        # #172: a linked git worktree has a `.git` FILE (a gitdir pointer), not a
        # dir, so the old `.git`-isdir check wrongly reported "is not a git repo" and
        # never synced. A worktree shares its parent's origin, so it must sync like
        # any checkout. (A first-class workflow in this repo per CLAUDE.md.)
        wt = os.path.join(self.tmp, "wt")
        r = _git(self.target, "worktree", "add", "-q", "--detach", wt, "HEAD")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(wt, ".git")))  # FILE, not dir
        out = self._run("exit", target=wt)
        self.assertNotIn("is not a git repo", out)
        self.assertIn("up to date", out)

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
        _rmtree(os.path.join(self.target, ".git"))   # Windows: git objects are read-only
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

    # --- content-layer sync (mirrors _team_sync's exact contract) -----------

    def test_content_layer_fast_forwards_when_configured_and_behind(self):
        self._advance_content_remote()
        # Ground truth is the SEED's HEAD, not the clone's own (never-yet-fetched,
        # therefore stale-but-internally-consistent) origin/main ref -- comparing
        # against the clone's own stale ref would pass even with zero fetch ever
        # happening, which is exactly the false-positive shape this suite exists
        # to avoid (np-kb-testing-ci §1).
        remote_tip = _git(self.content_seed, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(_git(self.content_dir, "rev-parse", "HEAD").stdout.strip(), remote_tip,
                            "test setup bug: clone already at remote tip before sync ran")
        self._run("exit", content_dir=self.content_dir)
        self.assertEqual(_git(self.content_dir, "rev-parse", "HEAD").stdout.strip(), remote_tip)

    def test_content_layer_dirty_skips_with_stderr_note(self):
        self._advance_content_remote()
        with open(os.path.join(self.content_dir, "dirty.txt"), "w") as fh:
            fh.write("x")
        before = _git(self.content_dir, "rev-parse", "HEAD").stdout.strip()
        _, err = self._run_full("exit", content_dir=self.content_dir)
        self.assertIn("content layer", err)
        self.assertIn("local edits", err)
        # never touched -- still behind origin, dirty file still present
        self.assertEqual(_git(self.content_dir, "rev-parse", "HEAD").stdout.strip(), before)
        self.assertTrue(os.path.isfile(os.path.join(self.content_dir, "dirty.txt")))

    def test_content_layer_ahead_is_reported_not_pushed(self):
        _git(self.content_dir, "commit", "-q", "--allow-empty", "-m", "content-local1")
        local_head = _git(self.content_dir, "rev-parse", "HEAD").stdout.strip()
        _, err = self._run_full("exit", content_dir=self.content_dir)
        self.assertIn("content layer", err)
        self.assertIn("not fast-forwarded", err)
        # never pushed -- the bare remote's main still doesn't know about local_head
        remote_main = _git(self.content_remote, "rev-parse", "main").stdout.strip()
        self.assertNotEqual(local_head, remote_main)

    def test_content_layer_unconfigured_is_a_silent_noop(self):
        # No NP_CONTENT_DIR, no config file -- content_is_explicit() is False, so
        # this must never touch any real directory (notably NOT the real engine
        # checkout content_dir() would otherwise fall back to).
        out, err = self._run_full("exit")
        self.assertIn("up to date", out)   # engine sync still ran normally
        self.assertNotIn("content layer", err)

    def test_content_layer_toggle_off_is_a_noop_even_when_behind(self):
        self._advance_content_remote()
        with open(self.conf, "w") as fh:
            fh.write("sync|shared|runtime|on|interval=86400,content=off\n")
        before = _git(self.content_dir, "rev-parse", "HEAD").stdout.strip()
        out, err = self._run_full("exit", content_dir=self.content_dir)
        self.assertIn("up to date", out)
        self.assertNotIn("content layer", err)
        self.assertEqual(_git(self.content_dir, "rev-parse", "HEAD").stdout.strip(), before)

    def test_content_layer_missing_directory_does_not_crash_engine_sync(self):
        # A stale NP_CONTENT_DIR (moved/deleted repo) must degrade gracefully --
        # the engine's own sync result must still come through on stdout.
        out = self._run("exit", content_dir=os.path.join(self.tmp, "does-not-exist"))
        self.assertIn("up to date", out)


if __name__ == "__main__":
    unittest.main()
