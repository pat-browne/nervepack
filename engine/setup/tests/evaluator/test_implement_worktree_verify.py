# np-test: implement-worktree-verify | `git worktree add` can exit 0 without
#          actually creating the worktree -- verify, don't infer, same as _agent_commit.
"""Live failure (2026-08-15, GitHub Actions Ubuntu runner): `git worktree add -q
-b <branch> <wt> <base>` returned exit code 0 with stderr `error: waitpid for
branch failed: No child processes`, and `<wt>` was never created. _attempt_repo
only checked the exit code, so it proceeded straight into the agent call with a
cwd that does not exist -- subprocess.Popen(cwd=<wt>) then raised a bare
FileNotFoundError, surfacing on the dashboard as the unhelpful "agent pass
raised: FileNotFoundError" instead of a clear worktree-creation failure.

Same principle as _agent_commit's docstring: verify the thing you depend on
actually exists rather than trusting a subprocess's exit code alone.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine")))

import np_implement_suggestion as imp  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True)


class TestWorktreeAddVerification(unittest.TestCase):
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
        self.log = os.path.join(self._tmp.name, "implement.log")

    def tearDown(self):
        self._tmp.cleanup()

    def test_phantom_success_is_treated_as_worktree_failed(self):
        """git reports rc=0 for `worktree add` but the directory never appears --
        must be caught before the agent is ever invoked, not surfaced as a
        confusing downstream FileNotFoundError."""
        real_git = imp._git
        agent_was_called = []

        def fake_git(repo, *args):
            if args[:2] == ("worktree", "add"):
                return subprocess.CompletedProcess(args, 0, "",
                    "error: waitpid for branch failed: No child processes\n")
            return real_git(repo, *args)

        def agent(prompt, tools, cwd, timeout):
            agent_was_called.append(cwd)
            return 0, "implemented", ""

        with mock.patch.object(imp, "_git", side_effect=fake_git):
            a = imp._attempt_repo(self.repo, "engine", "np-suggest/probe", "prompt", agent, self.log)

        self.assertEqual(a.state, "worktree_failed")
        self.assertEqual(agent_was_called, [], "the agent must never run against a cwd that doesn't exist")

    def test_real_worktree_add_still_works(self):
        """Guard against the verification itself being wrong: a real, successful
        worktree add must still reach the agent."""
        def agent(prompt, tools, cwd, timeout):
            self.assertTrue(os.path.isdir(cwd))
            return 0, "NOT_IMPLEMENTABLE: probe", ""

        a = imp._attempt_repo(self.repo, "engine", "np-suggest/probe", "prompt", agent, self.log)
        self.assertEqual(a.state, "not_implementable")


if __name__ == "__main__":
    unittest.main()
