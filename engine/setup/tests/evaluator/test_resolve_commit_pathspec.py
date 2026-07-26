"""Regression for issue #165 / #11: _default_resolve must path-limit its
staged-check AND its commit to the two ledger files, so a concurrent session's
unrelated staged change in the shared index is never swept into (and pushed
with) the resolve commit."""
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine")))

import np_implement_suggestion  # noqa: E402
import np_suggestion_resolve  # noqa: E402


class TestResolveCommitPathspec(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "t")
        os.makedirs(os.path.join(self.repo, "dashboard", "data"))
        self.ledger = os.path.join(self.repo, "dashboard", "data", "resolved-suggestions.txt")
        self.metrics = os.path.join(self.repo, "dashboard", "data", "metrics.js")
        self.unrelated_rel = "concurrent-wip.txt"
        self.unrelated = os.path.join(self.repo, self.unrelated_rel)
        for p in (self.ledger, self.metrics, self.unrelated):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("base\n")
        self._git("add", "-A")
        self._git("commit", "-qm", "base")

    def _git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args],
                              capture_output=True, text=True)

    def test_commit_excludes_concurrently_staged_file(self):
        # A concurrent session stages an UNRELATED change into the shared index.
        with open(self.unrelated, "a", encoding="utf-8") as fh:
            fh.write("another session's WIP\n")
        self._git("add", "--", self.unrelated_rel)

        # Stub resolve() to modify both ledger files (what the real one does),
        # and point default_ledger_path() at this repo via the env seam.
        def fake_resolve(text, *a, **k):
            for p in (self.ledger, self.metrics):
                with open(p, "a", encoding="utf-8") as fh:
                    fh.write("resolved\n")
        orig = np_suggestion_resolve.resolve
        np_suggestion_resolve.resolve = fake_resolve
        os.environ["NP_RESOLVED_SUGGESTIONS"] = self.ledger
        try:
            np_implement_suggestion._default_resolve("some suggestion")
        finally:
            np_suggestion_resolve.resolve = orig
            os.environ.pop("NP_RESOLVED_SUGGESTIONS", None)

        # The resolve commit must contain ONLY the two ledger files...
        changed = self._git("show", "--name-only", "--format=", "HEAD").stdout.split()
        self.assertIn("dashboard/data/resolved-suggestions.txt", changed)
        self.assertIn("dashboard/data/metrics.js", changed)
        self.assertNotIn(self.unrelated_rel, changed)
        # ...and the concurrent session's staged change must survive uncommitted.
        still_staged = self._git("diff", "--cached", "--name-only").stdout.split()
        self.assertIn(self.unrelated_rel, still_staged)


if __name__ == "__main__":
    unittest.main()
