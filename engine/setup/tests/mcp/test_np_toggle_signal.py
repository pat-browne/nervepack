"""Tests for np_toggle.signal() — the Python port of np-toggle-lib.sh's
np_signal bash function (appends a fire-marker line to the session signal
log, gated on evaluator.signals). Stdlib unittest."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import np_toggle  # noqa: E402


class TestSignal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|\n")
        self.sig_dir = os.path.join(self.tmp, "sig")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local"),
            "NP_SIGNAL_DIR": self.sig_dir,
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_appends_one_line(self):
        np_toggle.signal("s1", "skill-trigger-recall")
        with open(os.path.join(self.sig_dir, "s1.log")) as fh:
            self.assertEqual(fh.read(), "skill-trigger-recall\n")

    def test_appends_multiple_lines_in_order(self):
        np_toggle.signal("s1", "first")
        np_toggle.signal("s1", "second")
        with open(os.path.join(self.sig_dir, "s1.log")) as fh:
            self.assertEqual(fh.read(), "first\nsecond\n")

    def test_session_id_with_slash_is_sanitized(self):
        np_toggle.signal("proj/s1", "x")
        self.assertTrue(os.path.isfile(os.path.join(self.sig_dir, "proj_s1.log")))

    def test_noop_when_signals_toggle_off(self):
        with open(os.path.join(self.tmp, "local"), "w") as fh:
            fh.write("evaluator.signals=off\n")
        np_toggle.signal("s1", "x")
        self.assertFalse(os.path.isdir(self.sig_dir))

    def test_fail_open_on_unwritable_dir(self):
        # Point NP_SIGNAL_DIR at a path that can't be created (parent is a file).
        blocker = os.path.join(self.tmp, "blocker")
        open(blocker, "w").close()
        with mock.patch.dict(os.environ, {"NP_SIGNAL_DIR": os.path.join(blocker, "sig")}):
            np_toggle.signal("s1", "x")  # must not raise


if __name__ == "__main__":
    unittest.main()
