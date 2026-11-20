"""sync_push: a cron's commits reach origin after origin moved on.

Each test builds a bare origin, a local clone with a cron commit, and a second
clone that pushes first, so origin and local have diverged.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _SETUP)
sys.path.insert(0, os.path.normpath(os.path.join(_SETUP, "..", "nervepack_engine")))

import np_git_publish  # noqa: E402

JSONL = "dashboard/data/metrics.jsonl"
JS = "dashboard/data/metrics.js"


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), check=True,
                          capture_output=True, text=True).stdout.strip()


def _write(repo, rel, text, mode="w"):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as fh:
        fh.write(text)


def _commit(repo, msg, *paths):
    _git(repo, "add", *paths)
    _git(repo, "commit", "-q", "-m", msg)


def _count_regen(repo):
    """Stand-in for build.py: metrics.js holds the jsonl line count."""
    with open(os.path.join(repo, JSONL)) as fh:
        n = len([l for l in fh if l.strip()])
    _write(repo, JS, "window.N = %d;\n" % n)


class Diverged(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
               "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
               "NP_CRON_WORKTREES": os.path.join(d.name, "wts")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.bare = os.path.join(d.name, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.bare], check=True)
        seed = os.path.join(d.name, "seed")
        subprocess.run(["git", "clone", "-q", self.bare, seed], check=True,
                       capture_output=True)
        _git(seed, "switch", "-q", "-c", "main")
        _write(seed, JSONL, '{"id":1}\n')
        _write(seed, JS, "window.N = 1;\n")
        _write(seed, "skills/s/SKILL.md", "base\n")
        _commit(seed, "init", ".")
        _git(seed, "push", "-q", "origin", "HEAD:main")
        self.local = os.path.join(d.name, "local")
        self.other = os.path.join(d.name, "other")
        for c in (self.local, self.other):
            subprocess.run(["git", "clone", "-q", self.bare, c], check=True,
                           capture_output=True)

    def _origin_log(self):
        return _git(self.bare, "log", "--format=%s", "main")

    def _origin_file(self, rel):
        return _git(self.bare, "show", "main:" + rel)

    def test_unrelated_paths_rebase_and_publish(self):
        _write(self.other, "skills/t/SKILL.md", "theirs\n")
        _commit(self.other, "remote moved", ".")
        _git(self.other, "push", "-q", "origin", "HEAD:main")
        _write(self.local, "memory/x.md", "ours\n")
        _commit(self.local, "cron commit", ".")

        ok, why = np_git_publish.sync_push(self.local)
        self.assertTrue(ok, why)
        log = self._origin_log()
        self.assertIn("cron commit", log)
        self.assertIn("remote moved", log)
        self.assertEqual(_git(self.local, "rev-parse", "HEAD"),
                         _git(self.bare, "rev-parse", "main"))

    def test_jsonl_unions_and_generated_file_rebuilds(self):
        _write(self.other, JSONL, '{"id":2}\n', "a")
        _count_regen(self.other)
        _commit(self.other, "remote batch", ".")
        _git(self.other, "push", "-q", "origin", "HEAD:main")
        for i in (3, 4):
            _write(self.local, JSONL, '{"id":%d}\n' % i, "a")
            _count_regen(self.local)
            _commit(self.local, "cron batch %d" % i, ".")

        ok, why = np_git_publish.sync_push(self.local, regen=_count_regen)
        self.assertTrue(ok, why)
        rows = self._origin_file(JSONL).splitlines()
        self.assertEqual(sorted(rows), ['{"id":%d}' % i for i in (1, 2, 3, 4)])
        self.assertEqual(self._origin_file(JS), "window.N = 4;")
        self.assertIn("cron batch 4", self._origin_log())

    def test_unresolvable_conflict_aborts_and_keeps_commits(self):
        _write(self.other, "skills/s/SKILL.md", "theirs\n")
        _commit(self.other, "remote edit", ".")
        _git(self.other, "push", "-q", "origin", "HEAD:main")
        origin_before = _git(self.bare, "rev-parse", "main")
        _write(self.local, "skills/s/SKILL.md", "ours\n")
        _commit(self.local, "cron edit", ".")
        head_before = _git(self.local, "rev-parse", "HEAD")

        ok, why = np_git_publish.sync_push(self.local)
        self.assertFalse(ok)
        self.assertIn("skills/s/SKILL.md", why)
        self.assertIn("conflict", why)
        # Rebase aborted: local tip unchanged, no rebase left in progress.
        self.assertEqual(_git(self.local, "rev-parse", "HEAD"), head_before)
        gitdir = os.path.join(self.local, ".git")
        self.assertFalse(os.path.exists(os.path.join(gitdir, "rebase-merge")))
        self.assertFalse(os.path.exists(os.path.join(gitdir, "rebase-apply")))
        # Never forced: origin did not move.
        self.assertEqual(_git(self.bare, "rev-parse", "main"), origin_before)

    def test_nothing_to_push_is_ok(self):
        ok, why = np_git_publish.sync_push(self.local)
        self.assertTrue(ok, why)

    def test_publish_routes_through_sync(self):
        """push_to_main, the jobs' entry point, syncs before it pushes."""
        _write(self.other, JSONL, '{"id":2}\n', "a")
        _commit(self.other, "remote batch", ".")
        _git(self.other, "push", "-q", "origin", "HEAD:main")
        _write(self.local, JSONL, '{"id":3}\n', "a")
        _commit(self.local, "cron batch", ".")
        with mock.patch.object(np_git_publish, "rebuild_generated", _count_regen):
            ok, why = np_git_publish.publish(self.local)
        self.assertTrue(ok, why)
        self.assertEqual(len(self._origin_file(JSONL).splitlines()), 3)

    def test_cli_exits_nonzero_on_conflict(self):
        _write(self.other, "skills/s/SKILL.md", "theirs\n")
        _commit(self.other, "remote edit", ".")
        _git(self.other, "push", "-q", "origin", "HEAD:main")
        _write(self.local, "skills/s/SKILL.md", "ours\n")
        _commit(self.local, "cron edit", ".")
        r = subprocess.run([sys.executable, os.path.join(_SETUP, "np_git_publish.py"),
                            "push", self.local], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("conflict", r.stderr)


if __name__ == "__main__":
    unittest.main()
