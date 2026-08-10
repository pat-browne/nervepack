"""np_implement_suggestion: the "did the agent actually commit?" verdict.

Regression cover for a live failure (2026-08-10): three dashboard Implement
clicks logged `agent pass raised: FileNotFoundError` and then `implemented ->
main`, resolving the suggestions off the dashboard with nothing committed.
_attempt_repo inferred success from `end_sha != base_sha`, so a FAILED
`git rev-parse` (empty end_sha) read as a commit. _land then pushed
"<empty>:refs/heads/main", which git reads as DELETE THAT BRANCH.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine")))

import np_implement_suggestion as imp  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)


class _RepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self._tmp.name, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        with open(os.path.join(self.repo, "seed.txt"), "w") as fh:
            fh.write("seed\n")
        _git(self.repo, "add", "seed.txt")
        _git(self.repo, "commit", "-qm", "init")
        self.base_sha = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.log = os.path.join(self._tmp.name, "implement.log")

    def tearDown(self):
        self._tmp.cleanup()

    def _attempt(self, agent_fn, branch="np-suggest/probe"):
        return imp._attempt_repo(self.repo, "engine", branch, "prompt", agent_fn, self.log)


class TestVerdict(_RepoCase):
    def test_1_vanished_worktree_is_not_implemented(self):
        """The live bug: agent blows up AND its worktree is gone, so `git -C <wt>
        rev-parse HEAD` fails and end_sha is "". That must never read as a commit."""
        def agent(prompt, tools, cwd, timeout):
            shutil.rmtree(cwd, ignore_errors=True)
            raise FileNotFoundError(2, "No such file or directory")

        a = self._attempt(agent)
        self.assertNotEqual(a.state, "implemented", "empty end_sha must not read as a commit")
        self.assertEqual(a.agent_sha, "")

    def test_2_agent_error_is_not_implemented(self):
        def agent(prompt, tools, cwd, timeout):
            raise FileNotFoundError(2, "No such file or directory")

        a = self._attempt(agent)
        self.assertEqual(a.state, "no_commit")
        self.assertIn("agent", a.detail.lower())

    def test_3_agent_error_is_named_in_the_detail(self):
        """The status detail is the only thing the dashboard shows on failure, so the
        agent's own error has to survive into it rather than being logged and dropped."""
        def agent(prompt, tools, cwd, timeout):
            raise FileNotFoundError(2, "No such file or directory")

        a = self._attempt(agent)
        self.assertIn("FileNotFoundError", a.detail)

    def test_4_real_commit_is_implemented(self):
        def agent(prompt, tools, cwd, timeout):
            with open(os.path.join(cwd, "IMPL.txt"), "w") as fh:
                fh.write("done\n")
            _git(cwd, "add", "IMPL.txt")
            _git(cwd, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "feat: do it")
            return (0, "implemented", "")

        a = self._attempt(agent)
        self.assertEqual(a.state, "implemented")
        self.assertEqual(a.base_sha, self.base_sha)
        self.assertRegex(a.agent_sha, r"^[0-9a-f]{40}$")
        self.assertNotEqual(a.agent_sha, self.base_sha)

    def test_5_unrelated_sha_is_not_implemented(self):
        """A sha that isn't a descendant of base_sha isn't this agent's work — landing
        it would push an unrelated history over the base branch."""
        _git(self.repo, "checkout", "-q", "--orphan", "sideline")
        with open(os.path.join(self.repo, "other.txt"), "w") as fh:
            fh.write("other\n")
        _git(self.repo, "add", "other.txt")
        _git(self.repo, "commit", "-qm", "unrelated")
        stranger = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        _git(self.repo, "checkout", "-q", "main")

        def agent(prompt, tools, cwd, timeout):
            _git(cwd, "reset", "-q", "--hard", stranger)
            return (0, "", "")

        a = self._attempt(agent)
        self.assertNotEqual(a.state, "implemented")


class TestLandRefusesInvalidSha(_RepoCase):
    def test_1_land_never_pushes_an_empty_refspec(self):
        """`git push origin ':refs/heads/main'` DELETES main and exits 0. _land must
        refuse before it ever reaches the remote."""
        pushed = []

        def fake_git(repo, *args):
            if args and args[0] == "push":
                pushed.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        real_git = imp._git
        imp._git = fake_git
        try:
            ref = imp._land(self.repo, "engine", "direct", "np-suggest/probe", "main", "", self.log, None)
        finally:
            imp._git = real_git

        self.assertEqual(pushed, [], "no push may be attempted without a valid sha")
        self.assertEqual(ref, "np-suggest/probe")


if __name__ == "__main__":
    unittest.main()
