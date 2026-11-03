"""Crons never commit onto a non-main branch: write_root, cron_worktree, publish."""
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


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), check=True,
                          capture_output=True, text=True).stdout.strip()


def _repo(root):
    bare = os.path.join(root, "origin.git")
    local = os.path.join(root, "local")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", local], check=True)
    _git(local, "config", "user.email", "t@example.com")
    _git(local, "config", "user.name", "T")
    _git(local, "remote", "add", "origin", bare)
    with open(os.path.join(local, "f.txt"), "w") as fh:
        fh.write("one\n")
    _git(local, "add", "f.txt")
    _git(local, "commit", "-q", "-m", "init")
    _git(local, "push", "-q", "origin", "HEAD:main")
    return local, bare


class Base(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = self._d.name
        self.local, self.bare = _repo(self.root)
        env = {"NP_CRON_WORKTREES": os.path.join(self.root, "wts"),
               "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com",
               "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._d.cleanup)


class OffMain(Base):
    def test_main_is_none(self):
        self.assertIsNone(np_git_publish.off_main(self.local))

    def test_feature_branch_is_named(self):
        _git(self.local, "switch", "-q", "-c", "feat")
        self.assertEqual(np_git_publish.off_main(self.local), "feat")

    def test_detached_is_named(self):
        _git(self.local, "checkout", "-q", "--detach")
        self.assertEqual(np_git_publish.off_main(self.local), "detached HEAD")

    def test_repo_without_main_is_none(self):
        other = os.path.join(self.root, "nomain")
        subprocess.run(["git", "init", "-q", "-b", "master", other], check=True)
        self.assertIsNone(np_git_publish.off_main(other))

    def test_non_repo_is_none(self):
        self.assertIsNone(np_git_publish.off_main(os.path.join(self.root, "wts")))


class WriteRoot(Base):
    def test_on_main_returns_repo(self):
        self.assertEqual(np_git_publish.write_root(self.local, "t"), (self.local, ""))

    def test_off_main_commit_lands_on_origin_main_not_branch(self):
        _git(self.local, "switch", "-q", "-c", "feat")
        feat_before = _git(self.local, "rev-parse", "feat")
        wt, note = np_git_publish.write_root(self.local, "t")
        self.assertNotEqual(wt, self.local)
        self.assertIn("feat", note)
        with open(os.path.join(wt, "g.txt"), "w") as fh:
            fh.write("cron\n")
        _git(wt, "add", "g.txt")
        _git(wt, "commit", "-q", "-m", "cron", "--", "g.txt")
        self.assertEqual(np_git_publish.publish(wt), (True, ""))
        self.assertEqual(_git(self.local, "rev-parse", "feat"), feat_before)
        self.assertIn("g.txt", _git(self.bare, "ls-tree", "--name-only", "main"))

    def test_reuse_fast_forwards_and_cleans(self):
        _git(self.local, "switch", "-q", "-c", "feat")
        wt, _ = np_git_publish.write_root(self.local, "t")
        with open(os.path.join(wt, "junk.txt"), "w") as fh:
            fh.write("x\n")
        other = os.path.join(self.root, "other")
        subprocess.run(["git", "clone", "-q", self.bare, other], check=True)
        with open(os.path.join(other, "h.txt"), "w") as fh:
            fh.write("h\n")
        _git(other, "add", "h.txt")
        _git(other, "commit", "-q", "-m", "h")
        _git(other, "push", "-q", "origin", "HEAD:main")
        wt2, _ = np_git_publish.write_root(self.local, "t")
        self.assertEqual(wt, wt2)
        self.assertTrue(os.path.exists(os.path.join(wt2, "h.txt")))
        self.assertFalse(os.path.exists(os.path.join(wt2, "junk.txt")))

    def test_conflicting_stranded_commit_is_parked_not_wedged(self):
        _git(self.local, "switch", "-q", "-c", "feat")
        wt, _ = np_git_publish.write_root(self.local, "t")
        with open(os.path.join(wt, "f.txt"), "w") as fh:
            fh.write("cron\n")
        _git(wt, "commit", "-q", "-am", "stranded")
        other = os.path.join(self.root, "other")
        subprocess.run(["git", "clone", "-q", self.bare, other], check=True)
        with open(os.path.join(other, "f.txt"), "w") as fh:
            fh.write("remote\n")
        _git(other, "commit", "-q", "-am", "remote")
        _git(other, "push", "-q", "origin", "HEAD:main")
        wt2, _ = np_git_publish.write_root(self.local, "t")
        self.assertEqual(wt2, wt)
        self.assertEqual(_git(wt, "rev-parse", "HEAD"),
                         _git(self.local, "rev-parse", "origin/main"))
        self.assertIn("refs/nervepack/stranded/",
                      _git(self.local, "for-each-ref", "refs/nervepack"))

    def test_failure_returns_none_never_raises(self):
        _git(self.local, "switch", "-q", "-c", "feat")
        with mock.patch.object(np_git_publish, "cron_worktree",
                               return_value=(None, "boom")):
            wt, note = np_git_publish.write_root(self.local, "t")
        self.assertIsNone(wt)
        self.assertIn("boom", note)

    def test_live_checkout_publish_still_guarded(self):
        _git(self.local, "switch", "-q", "-c", "feat")
        ok, why = np_git_publish.publish(self.local)
        self.assertFalse(ok)
        self.assertIn("refused", why)


class AgenticCronRefuses(Base):
    def test_refusal_names_branch(self):
        import np_agentic_cron
        _git(self.local, "switch", "-q", "-c", "feat")
        cfg = np_agentic_cron.CronConfig(
            name="x", toggle="x", prompt_rel_path="x", log_env="NP_TEST_LOG_X",
            log_basename="x.log")
        with mock.patch.dict(os.environ,
                             {"NP_TEST_LOG_X": os.path.join(self.root, "x.log")}):
            status = np_agentic_cron._off_main_refusal(cfg, self.local)
        self.assertIn("feat", status)
        with open(os.path.join(self.root, "x.log")) as fh:
            self.assertIn("REFUSED", fh.read())

    def test_non_committing_cron_not_refused(self):
        import np_agentic_cron
        _git(self.local, "switch", "-q", "-c", "feat")
        cfg = np_agentic_cron.CronConfig(
            name="x", toggle="x", prompt_rel_path="x", log_env="NP_TEST_LOG_X",
            log_basename="x.log", commits_in_target=False)
        self.assertEqual(np_agentic_cron._off_main_refusal(cfg, self.local), "")


if __name__ == "__main__":
    unittest.main()
