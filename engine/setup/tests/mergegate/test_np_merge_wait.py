"""Direct unit tests for np_merge_wait.py -- port of np-merge-wait.sh, the
concurrency merge-gate waiter. Ports the 4 scenarios from
test_merge_wait.sh: clean->CLEAN, conflict->ISSUES, AI-trailer->ISSUES,
never-settles->TIMEOUT."""
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_merge_wait  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                    capture_output=True, text=True)


def _build_repo(repo, mode):
    os.makedirs(repo, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    with open(os.path.join(repo, "f"), "w") as fh:
        fh.write("x=a\n")
    _git(repo, "add", "f")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    if mode == "clean":
        with open(os.path.join(repo, "g"), "w") as fh:
            fh.write("new\n")
        _git(repo, "add", "g")
        _git(repo, "commit", "-qm", "add g")
    elif mode == "conflict":
        with open(os.path.join(repo, "f"), "w") as fh:
            fh.write("x=b\n")
        _git(repo, "add", "f")
        _git(repo, "commit", "-qm", "feature edit")
        _git(repo, "checkout", "-q", "main")
        with open(os.path.join(repo, "f"), "w") as fh:
            fh.write("x=c\n")
        _git(repo, "add", "f")
        _git(repo, "commit", "-qm", "base edit")
    elif mode == "trailer":
        with open(os.path.join(repo, "g"), "w") as fh:
            fh.write("new\n")
        _git(repo, "add", "g")
        _git(repo, "commit", "-qm",
             "add g\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>")


class TestMergeWait(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_1_clean_repo_settles_and_merges_clean(self):
        repo = os.path.join(self.tmp, "r1")
        _build_repo(repo, "clean")
        code, lines = np_merge_wait.wait_and_check(
            repo, branch="feature", base="main", interval=0, settle=2, timeout=5)
        self.assertEqual(code, 0)
        self.assertTrue(any("RESULT: CLEAN" in ln for ln in lines))

    def test_2_conflict_reports_issues(self):
        repo = os.path.join(self.tmp, "r2")
        _build_repo(repo, "conflict")
        code, lines = np_merge_wait.wait_and_check(
            repo, branch="feature", base="main", interval=0, settle=2, timeout=5)
        self.assertEqual(code, 2)
        joined = "\n".join(lines)
        self.assertIn("RESULT: ISSUES", joined)
        self.assertIn("conflict", joined.lower())

    def test_3_ai_trailer_reports_issues(self):
        repo = os.path.join(self.tmp, "r3")
        _build_repo(repo, "trailer")
        code, lines = np_merge_wait.wait_and_check(
            repo, branch="feature", base="main", interval=0, settle=2, timeout=5)
        self.assertEqual(code, 2)
        self.assertIn("trailer", "\n".join(lines).lower())

    def test_4_never_settles_times_out(self):
        repo = os.path.join(self.tmp, "r4")
        _build_repo(repo, "clean")
        counter = {"n": 0}

        def _state_cmd(_repo):
            counter["n"] += 1
            return str(counter["n"])

        code, lines = np_merge_wait.wait_and_check(
            repo, branch="feature", base="main", interval=0, backoff=0,
            settle=2, timeout=1, state_cmd=_state_cmd)
        self.assertEqual(code, 3)
        self.assertTrue(any("RESULT: TIMEOUT" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
