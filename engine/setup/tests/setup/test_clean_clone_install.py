#!/usr/bin/env python3
# np-test: clean-clone | happy
"""Prove a clean clone at an arbitrary path registers working hooks (F11/#257).

#295 replaced the literal `~/Code/nervepack` in every hooks.manifest row with a
`{NP_DIR}` token substituted from the resolved root. This test is the acceptance
criterion for that change: **CI proves a clean-clone install from a path that is
not ~/Code/nervepack.**

It is written as a test rather than a CI job on purpose. `regression` and
`windows` are both required checks and both already run this directory, so the
property is enforced on Linux AND on the Git-bash lane without adding a job that
would have to be added to the ruleset separately.

Why a copy of the tree rather than calling install_hooks() in process: the whole
question is what `np_paths.REPO_ROOT` resolves to, and that is computed at import
from the module's own `__file__`. An in-process call would resolve to THIS
checkout no matter what path the test pretends to use, and would pass while
proving nothing. The subprocess has to be the copy's own interpreter entry point.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))

# Everything install-hooks needs, and nothing else. Copying .git would triple the
# runtime for no coverage: the installer never shells out to git.
_NEEDED = ("engine",)


def _clone_to(dest):
    """A checkout of this tree at `dest`, without .git or any worktree."""
    os.makedirs(dest, exist_ok=True)
    for name in _NEEDED:
        src = os.path.join(_REPO, name)
        shutil.copytree(
            src, os.path.join(dest, name),
            ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__",
                                          "*.pyc", "tests"))
    return dest


def _commands(settings):
    out = []
    for rows in (settings.get("hooks") or {}).values():
        for entry in rows:
            for hook in entry.get("hooks", []):
                command = hook.get("command")
                # Skip a row with no command rather than appending "". An empty
                # string would inflate the count comparison below, turning a
                # malformed registration into a passing test.
                if command:
                    out.append(command)
    return out


class TestACleanCloneRegistersAgainstItsOwnPath(unittest.TestCase):
    """The failure this guards against is silent. Before #295 every row carried
    `~/Code/nervepack` literally, so a clone anywhere else registered 26 hooks
    pointing at a directory that does not exist -- and hooks fail open, so
    nothing errored and nothing went red."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="np-clean-clone-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # Deliberately not ~/Code/nervepack, and deliberately a name that shares
        # no component with it.
        self.root = _clone_to(os.path.join(self.tmp, "elsewhere", "np"))
        self.settings = os.path.join(self.tmp, "settings.json")

    def _install(self):
        env = dict(os.environ, CLAUDE_SETTINGS=self.settings)
        env["NP_HOOK_WRAP"] = "0"     # pin the unwrapped form on every kernel
        env.pop("NP_DIR", None)
        env.pop("NERVEPACK", None)
        cli = os.path.join(self.root, "engine", "nervepack_engine", "cli.py")
        # Pre-flight, so a copy that silently lost a file fails HERE with a
        # sentence rather than downstream as an opaque non-zero exit.
        self.assertTrue(os.path.isfile(cli), "the copy has no cli.py at %s" % cli)
        try:
            result = subprocess.run([sys.executable, cli, "setup", "install-hooks"],
                                    env=env, capture_output=True, text=True,
                                    errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            # Fail fast with a sentence instead of leaning on the job-level
            # timeout, which is measured in hours and says nothing about which
            # test was running.
            self.fail("install-hooks did not finish within 120s (root=%s)" % self.root)
        # An exit code on its own is not diagnosable from a CI log, and this test
        # runs on a lane that cannot be reproduced locally. Say everything.
        self.assertEqual(
            result.returncode, 0,
            "install-hooks exited %s\n"
            "  interpreter: %s\n"
            "  cli:         %s\n"
            "  root:        %s\n"
            "  settings:    %s (exists=%s)\n"
            "  stdout:      %r\n"
            "  stderr:      %r"
            % (result.returncode, sys.executable, cli, self.root, self.settings,
               os.path.exists(self.settings), result.stdout, result.stderr))
        with open(self.settings, encoding="utf-8") as fh:
            return json.load(fh), result

    def test_every_command_points_at_the_clone(self):
        settings, _ = self._install()
        commands = [c for c in _commands(settings) if "cli.py" in c]
        self.assertTrue(commands, "no hook commands were registered at all")
        expected = self.root.replace("\\", "/")
        for command in commands:
            self.assertIn(expected, command, command)

    def test_no_command_mentions_the_old_assumed_location(self):
        settings, _ = self._install()
        for command in _commands(settings):
            self.assertNotIn("Code/nervepack", command, command)

    def test_no_command_still_carries_the_token(self):
        """An unsubstituted {NP_DIR} would be a literal directory name."""
        settings, _ = self._install()
        for command in _commands(settings):
            self.assertNotIn("{NP_DIR}", command, command)

    def test_the_registered_paths_exist_on_disk(self):
        """The point of the whole exercise: the command has to actually resolve.
        Asserting the string alone would pass on a path that is merely
        well-formed."""
        settings, _ = self._install()
        for command in _commands(settings):
            if "cli.py" not in command:
                continue
            for token in command.split():
                if token.endswith("cli.py"):
                    self.assertTrue(os.path.isfile(token),
                                    "registered a path that does not exist: %s" % token)
                    break

    def test_it_reports_the_root_it_registered_against(self):
        _, result = self._install()
        self.assertIn("registering hooks rooted at", result.stderr)
        self.assertIn(self.root.replace("\\", "/"), result.stderr.replace("\\", "/"))

    def test_the_same_count_is_registered_as_from_the_real_checkout(self):
        """A clone must not register FEWER hooks than the original. Equal counts
        are what makes 'it works elsewhere' mean the same thing as 'it works'."""
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))
        sys.path.insert(0, os.path.join(_REPO, "engine", "setup"))
        sys.path.insert(0, os.path.join(_REPO, "engine", "nervepack_engine"))
        import np_hook
        expected = len(np_hook.read_manifest())
        settings, _ = self._install()
        self.assertEqual(len(_commands(settings)), expected)


if __name__ == "__main__":
    unittest.main()
