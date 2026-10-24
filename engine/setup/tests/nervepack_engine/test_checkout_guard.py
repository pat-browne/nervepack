"""Tests for np_checkout_guard and the checkout-guard SessionStart hook, using
real temp git repos (origin + clone)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_checkout_guard as g  # noqa: E402
from nervepack_engine.hooks import checkout_guard  # noqa: E402


def sh(*a, cwd=None):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def commit(repo, name):
    with open(os.path.join(repo, name), "w") as f:
        f.write(name)
    sh("git", "add", ".", cwd=repo)
    sh("git", "-c", "user.email=t@e.c", "-c", "user.name=T", "commit", "-qm", name, cwd=repo)


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = os.path.join(self.tmp, "origin")
        os.makedirs(self.origin)
        sh("git", "init", "-q", "-b", "main", cwd=self.origin)
        commit(self.origin, "a")
        self.clone = os.path.join(self.tmp, "clone")
        sh("git", "clone", "-q", self.origin, self.clone)

    def advance_origin(self, n):
        for i in range(n):
            commit(self.origin, "n%d" % i)
        sh("git", "fetch", "-q", cwd=self.clone)

    def test_main_up_to_date_no_warning(self):
        info = g.check(self.clone)
        self.assertEqual((info["branch"], info["behind"], info["dirty"]), ("main", 0, False))
        self.assertEqual(g.warning([info]), "")

    def test_feature_branch_warns(self):
        sh("git", "checkout", "-qb", "contrib/x", cwd=self.clone)
        w = g.warning([g.check(self.clone)])
        self.assertIn("contrib/x", w)
        self.assertIn("git -C <repo> show origin/main:<path>", w)

    def test_behind_warns_with_count(self):
        self.advance_origin(3)
        info = g.check(self.clone)
        self.assertEqual(info["behind"], 3)
        self.assertIn("3 commit(s) behind", g.warning([info]))

    def test_dirty_reported(self):
        with open(os.path.join(self.clone, "u"), "w") as f:
            f.write("x")
        self.assertTrue(g.check(self.clone)["dirty"])

    def test_not_a_repo_is_skipped(self):
        self.assertIsNone(g.check(self.tmp + "/nope"))

    def test_scan_does_not_fetch_but_doctor_does(self):
        commit(self.origin, "later")  # clone has not fetched
        self.assertEqual(g.check(self.clone)["behind"], 0)
        self.assertEqual(g.check(self.clone, fetch=True)["behind"], 1)

    def test_hook_silent_when_clean_and_loud_when_stale(self):
        orig = g.checkouts
        self.addCleanup(setattr, g, "checkouts", orig)
        g.checkouts = lambda: [self.clone]
        self.assertEqual(checkout_guard.run(""), "")
        self.advance_origin(2)
        out = json.loads(checkout_guard.run(""))
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("2 commit(s) behind", ctx)

    def test_hook_silent_when_toggle_off(self):
        import np_toggle
        orig = g.checkouts
        self.addCleanup(setattr, g, "checkouts", orig)
        g.checkouts = lambda: [self.clone]
        self.advance_origin(1)
        orig_en = np_toggle.enabled
        self.addCleanup(setattr, np_toggle, "enabled", orig_en)
        np_toggle.enabled = lambda f, *a, **k: f != "checkout"
        self.assertEqual(checkout_guard.run(""), "")

    def test_doctor_status_warn_and_pass(self):
        orig = g.checkouts
        self.addCleanup(setattr, g, "checkouts", orig)
        g.checkouts = lambda: [self.clone]
        self.assertTrue(g.doctor_status().startswith("PASS"))
        commit(self.origin, "later")
        self.assertTrue(g.doctor_status().startswith("WARN"))


if __name__ == "__main__":
    unittest.main()
