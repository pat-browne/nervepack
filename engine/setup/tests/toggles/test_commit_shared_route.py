"""np_toggle.commit_shared never commits onto a non-main branch."""
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

import np_toggle  # noqa: E402

CONF = "memory|shared|runtime|on|\nsync|shared|runtime|on|\n"


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), check=True,
                          capture_output=True, text=True).stdout.strip()


class CommitSharedRoute(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        root = self._d.name
        self.bare = os.path.join(root, "origin.git")
        self.repo = os.path.join(root, "repo")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.bare], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "T")
        _git(self.repo, "remote", "add", "origin", self.bare)
        self.conf = os.path.join(self.repo, "toggles.conf")
        with open(self.conf, "w") as fh:
            fh.write(CONF)
        _git(self.repo, "add", "toggles.conf")
        _git(self.repo, "commit", "-q", "-m", "init")
        _git(self.repo, "push", "-q", "origin", "HEAD:main")
        env = {"NP_TOGGLES_CONF": self.conf, "NP_TOGGLES_CONTENT": "",
               "NP_CRON_WORKTREES": os.path.join(root, "wts"),
               "NP_TOGGLE_NO_COMMIT": "", "XDG_CACHE_HOME": os.path.join(root, "cache")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)

    def _flip(self):
        np_toggle.set_conf_state("memory", "off")
        np_toggle.commit_shared("toggle(memory): off", replay=("state", "memory", "off"))

    def _origin_conf(self):
        return _git(self.bare, "show", "main:toggles.conf")

    def test_on_main_commits_and_publishes(self):
        self._flip()
        self.assertIn("memory|shared|runtime|off|", self._origin_conf())
        self.assertEqual(_git(self.repo, "log", "-1", "--format=%s"), "toggle(memory): off")

    def test_off_main_leaves_the_branch_alone_and_lands_on_origin_main(self):
        _git(self.repo, "switch", "-q", "-c", "feat")
        tip = _git(self.repo, "rev-parse", "feat")
        self._flip()
        self.assertEqual(_git(self.repo, "rev-parse", "feat"), tip)
        self.assertIn("memory|shared|runtime|off|", self._origin_conf())
        self.assertEqual(_git(self.bare, "log", "-1", "--format=%s", "main"),
                         "toggle(memory): off")

    def test_off_main_keeps_the_live_edit_so_the_toggle_applies(self):
        _git(self.repo, "switch", "-q", "-c", "feat")
        self._flip()
        self.assertFalse(np_toggle.enabled("memory"))

    def test_off_main_replays_only_the_flip_not_the_branch_version(self):
        other = os.path.join(self._d.name, "other")
        subprocess.run(["git", "clone", "-q", self.bare, other], check=True)
        _git(other, "config", "user.email", "t@example.com")
        _git(other, "config", "user.name", "T")
        with open(os.path.join(other, "toggles.conf"), "a") as fh:
            fh.write("added|shared|runtime|on|\n")
        _git(other, "commit", "-q", "-am", "add row")
        _git(other, "push", "-q", "origin", "HEAD:main")
        _git(self.repo, "switch", "-q", "-c", "feat")
        self._flip()
        merged = self._origin_conf()
        self.assertIn("added|shared|runtime|on|", merged)
        self.assertIn("memory|shared|runtime|off|", merged)

    def _dirty(self):
        with open(self.conf, "a") as fh:
            fh.write("private|shared|runtime|on|secret=1\n")

    def test_off_main_unrelated_dirty_edit_never_reaches_origin(self):
        _git(self.repo, "switch", "-q", "-c", "feat")
        self._dirty()
        self._flip()
        merged = self._origin_conf()
        self.assertIn("memory|shared|runtime|off|", merged)
        self.assertNotIn("private", merged)
        with open(self.conf) as fh:
            self.assertIn("private|shared", fh.read())

    def test_on_main_unrelated_dirty_edit_is_refused(self):
        self._dirty()
        self._flip()
        self.assertNotIn("memory|shared|runtime|off|", self._origin_conf())
        self.assertEqual(_git(self.repo, "log", "-1", "--format=%s"), "init")

    def test_param_flip_replays_one_row(self):
        _git(self.repo, "switch", "-q", "-c", "feat")
        self._dirty()
        np_toggle.set_conf_param("memory.promote", "off")
        np_toggle.commit_shared("toggle(memory.promote): off",
                                replay=("param", "memory.promote", "off"))
        merged = self._origin_conf()
        self.assertIn("promote=off", merged)
        self.assertNotIn("private", merged)

    def test_missing_replay_commits_nothing(self):
        np_toggle.set_conf_state("memory", "off")
        np_toggle.commit_shared("toggle(memory): off")
        self.assertEqual(_git(self.repo, "log", "-1", "--format=%s"), "init")

    def test_no_commit_env_is_a_noop(self):
        with mock.patch.dict(os.environ, {"NP_TOGGLE_NO_COMMIT": "1"}):
            self._flip()
        self.assertEqual(_git(self.repo, "log", "-1", "--format=%s"), "init")


if __name__ == "__main__":
    unittest.main()
