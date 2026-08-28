"""Unit tests for np_git_publish -- the branch guard on the crons' publish step.

Regression cover for the 2026-08-28 incident: three scheduled writers pushed
`HEAD:main` without checking that HEAD was main, and discarded the result. On a
checkout parked 198 commits behind main, every push was a rejected
non-fast-forward and every job still exited 0. Thirty-three commits stranded
locally over two days with no log line saying so."""
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine")))

import np_git_publish  # noqa: E402


def _run(*args, **kw):
    subprocess.run(list(args), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def _repo_with_origin(root):
    """A `local` repo on main whose origin is a bare repo. Returns local path."""
    bare = os.path.join(root, "origin.git")
    local = os.path.join(root, "local")
    _run("git", "init", "-q", "--bare", "-b", "main", bare)
    _run("git", "init", "-q", "-b", "main", local)
    _run("git", "-C", local, "config", "user.email", "t@example.com")
    _run("git", "-C", local, "config", "user.name", "T")
    _run("git", "-C", local, "remote", "add", "origin", bare)
    with open(os.path.join(local, "f.txt"), "w") as fh:
        fh.write("one\n")
    _run("git", "-C", local, "add", "f.txt")
    _run("git", "-C", local, "commit", "-q", "-m", "init")
    _run("git", "-C", local, "push", "-q", "origin", "HEAD:main")
    return local, bare


class CurrentBranch(unittest.TestCase):
    def test_reports_the_branch_name(self):
        with tempfile.TemporaryDirectory() as d:
            local, _ = _repo_with_origin(d)
            self.assertEqual(np_git_publish.current_branch(local), "main")

    def test_detached_head_reads_as_none(self):
        with tempfile.TemporaryDirectory() as d:
            local, _ = _repo_with_origin(d)
            sha = subprocess.run(["git", "-C", local, "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()
            _run("git", "-C", local, "checkout", "-q", "--detach", sha)
            self.assertIsNone(np_git_publish.current_branch(local))

    def test_non_repo_reads_as_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(np_git_publish.current_branch(d))


class PushToMain(unittest.TestCase):
    def test_publishes_from_main(self):
        with tempfile.TemporaryDirectory() as d:
            local, bare = _repo_with_origin(d)
            with open(os.path.join(local, "f.txt"), "a") as fh:
                fh.write("two\n")
            _run("git", "-C", local, "commit", "-q", "-am", "second")
            ok, why = np_git_publish.push_to_main(local)
            self.assertTrue(ok, why)
            self.assertEqual(why, "")
            remote = subprocess.run(["git", "-C", bare, "log", "--oneline", "main"],
                                    capture_output=True, text=True).stdout
            self.assertIn("second", remote)

    def test_refuses_on_a_feature_branch_and_says_which(self):
        """THE INCIDENT. The commit must stay local and the reason must be returned."""
        with tempfile.TemporaryDirectory() as d:
            local, bare = _repo_with_origin(d)
            _run("git", "-C", local, "checkout", "-q", "-b", "capture/something")
            with open(os.path.join(local, "f.txt"), "a") as fh:
                fh.write("stranded\n")
            _run("git", "-C", local, "commit", "-q", "-am", "cron output")
            ok, why = np_git_publish.push_to_main(local)
            self.assertFalse(ok)
            self.assertIn("capture/something", why)
            self.assertIn("safe locally", why)
            remote = subprocess.run(["git", "-C", bare, "log", "--oneline", "main"],
                                    capture_output=True, text=True).stdout
            self.assertNotIn("cron output", remote)

    def test_refuses_on_detached_head(self):
        with tempfile.TemporaryDirectory() as d:
            local, _ = _repo_with_origin(d)
            sha = subprocess.run(["git", "-C", local, "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip()
            _run("git", "-C", local, "checkout", "-q", "--detach", sha)
            ok, why = np_git_publish.push_to_main(local)
            self.assertFalse(ok)
            self.assertIn("detached", why)

    def test_surfaces_a_rejected_push_instead_of_swallowing_it(self):
        """On main, but the remote moved ahead: git rejects, and we must say so."""
        with tempfile.TemporaryDirectory() as d:
            local, bare = _repo_with_origin(d)
            other = os.path.join(d, "other")
            _run("git", "clone", "-q", bare, other)
            _run("git", "-C", other, "config", "user.email", "t@example.com")
            _run("git", "-C", other, "config", "user.name", "T")
            with open(os.path.join(other, "f.txt"), "a") as fh:
                fh.write("remote-side\n")
            _run("git", "-C", other, "commit", "-q", "-am", "remote moved")
            _run("git", "-C", other, "push", "-q", "origin", "HEAD:main")

            with open(os.path.join(local, "f.txt"), "a") as fh:
                fh.write("local-side\n")
            _run("git", "-C", local, "commit", "-q", "-am", "local diverged")
            ok, why = np_git_publish.push_to_main(local)
            self.assertFalse(ok)
            self.assertIn("rejected", why)
            self.assertNotEqual(why.strip(), "push rejected:")

    def test_never_raises_on_a_missing_path(self):
        ok, why = np_git_publish.push_to_main("/nonexistent/path/xyz")
        self.assertFalse(ok)
        self.assertTrue(why)


if __name__ == "__main__":
    unittest.main()
