"""Direct unit tests for np_link_dashboard_data.py -- port of
35-link-dashboard-data.sh. Ports the 5 cases from
test_link_dashboard_data.sh: fresh-clone creates symlink, idempotent re-run,
wrong-target replaced, single-repo layout no-op, fail-open on bad content
dir. Unlike the bash test, this operates entirely on temp directories --
np_root/content_dir_fn are explicit parameters, so the real repo's
dashboard/data is never touched."""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_link_dashboard_data  # noqa: E402


class TestLinkDashboardData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.np_root = os.path.join(self.tmp, "engine")
        os.makedirs(os.path.join(self.np_root, "dashboard"))
        self.content_dir = os.path.join(self.tmp, "content")
        os.makedirs(self.content_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _link_path(self):
        return os.path.join(self.np_root, "dashboard", "data")

    def _readlink_normalized(self, link):
        # os.readlink() on Windows can return the extended-length-path form
        # (\\?\C:\...) even for a symlink created from a normal path -- a
        # Windows-only path-normalization detail unrelated to whether the
        # symlink actually points at the right place. Strip it before
        # comparing so the test isn't sensitive to this. Confirmed on real
        # Windows CI (a correct symlink otherwise failed a raw string
        # equality check against the un-prefixed target path).
        target = os.readlink(link)
        if target.startswith("\\\\?\\"):
            target = target[4:]
        return os.path.normpath(target)

    def test_1_fresh_clone_creates_symlink(self):
        code = np_link_dashboard_data.link(np_root=self.np_root, content_dir_fn=lambda: self.content_dir)
        self.assertEqual(code, 0)
        link = self._link_path()
        self.assertTrue(os.path.islink(link))
        target = self._readlink_normalized(link)
        self.assertEqual(target, os.path.normpath(os.path.join(self.content_dir, "dashboard", "data")))
        self.assertTrue(os.path.isdir(target))

    def test_2_idempotent_rerun(self):
        np_link_dashboard_data.link(np_root=self.np_root, content_dir_fn=lambda: self.content_dir)
        code = np_link_dashboard_data.link(np_root=self.np_root, content_dir_fn=lambda: self.content_dir)
        self.assertEqual(code, 0)
        link = self._link_path()
        self.assertTrue(os.path.islink(link))
        self.assertEqual(self._readlink_normalized(link),
                         os.path.normpath(os.path.join(self.content_dir, "dashboard", "data")))

    def test_3_wrong_target_replaced(self):
        wrong_target = os.path.join(self.tmp, "wrong-target-xyz")
        os.makedirs(wrong_target)
        os.symlink(wrong_target, self._link_path())
        code = np_link_dashboard_data.link(np_root=self.np_root, content_dir_fn=lambda: self.content_dir)
        self.assertEqual(code, 0)
        link = self._link_path()
        self.assertTrue(os.path.islink(link))
        self.assertEqual(self._readlink_normalized(link),
                         os.path.normpath(os.path.join(self.content_dir, "dashboard", "data")))

    def test_4_single_repo_layout_is_noop(self):
        # content dir == engine root -- mirrors test_link_dashboard_data.sh's
        # Case 4, which mkdir -p's the real dashboard/data dir before running
        # since the single-repo layout always has it in place already. A
        # symlink here would be self-referential.
        os.makedirs(self._link_path())
        code = np_link_dashboard_data.link(np_root=self.np_root, content_dir_fn=lambda: self.np_root)
        self.assertEqual(code, 0)
        link = self._link_path()
        self.assertFalse(os.path.islink(link))
        self.assertTrue(os.path.isdir(link))

    def test_5_fail_open_on_bad_content_dir(self):
        def _raise():
            raise OSError("no such content dir")
        code = np_link_dashboard_data.link(np_root=self.np_root, content_dir_fn=_raise)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.islink(self._link_path()))


if __name__ == "__main__":
    unittest.main()
