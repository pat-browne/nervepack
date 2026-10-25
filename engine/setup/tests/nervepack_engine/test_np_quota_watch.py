"""Tests for np_quota_watch.py -- the usage-limit detector and resume nudge."""
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_quota_watch  # noqa: E402


class FindResetEpochTests(unittest.TestCase):
    def test_finds_the_reset_timestamp(self):
        text = "noise\nClaude AI usage limit reached|1717027200\nmore noise"
        self.assertEqual(np_quota_watch.find_reset_epoch(text), 1717027200.0)

    def test_treats_a_13_digit_value_as_milliseconds(self):
        text = "Claude AI usage limit reached|1717027200000"
        self.assertEqual(np_quota_watch.find_reset_epoch(text), 1717027200.0)

    def test_returns_none_with_no_signal(self):
        self.assertIsNone(np_quota_watch.find_reset_epoch("nothing to see here"))

    def test_takes_the_latest_match(self):
        text = "usage limit reached|1717027100\nusage limit reached|1717027200"
        self.assertEqual(np_quota_watch.find_reset_epoch(text), 1717027200.0)


class DetectAndScheduleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.object(np_quota_watch.np_dirs, "cache_path",
                                     side_effect=lambda *p: os.path.join(self._tmp.name, *p))
        patcher.start()
        self.addCleanup(patcher.stop)
        toggle_patcher = mock.patch.object(np_quota_watch.np_toggle, "enabled", return_value=True)
        toggle_patcher.start()
        self.addCleanup(toggle_patcher.stop)
        param_patcher = mock.patch.object(np_quota_watch.np_toggle, "param", return_value="60")
        param_patcher.start()
        self.addCleanup(param_patcher.stop)

    def test_no_signal_leaves_state_untouched(self):
        self.assertEqual(np_quota_watch.detect_and_schedule("nothing here", "test"), "no signal")
        self.assertEqual(np_quota_watch._load_state(), {})

    def test_disabled_toggle_skips(self):
        with mock.patch.object(np_quota_watch.np_toggle, "enabled", return_value=False):
            text = "usage limit reached|1717027200"
            self.assertEqual(np_quota_watch.detect_and_schedule(text, "test"),
                              "skipped: quota_watch disabled")

    def test_schedules_and_records_state(self):
        with mock.patch.object(np_quota_watch, "_schedule_at", return_value=False):
            text = "usage limit reached|1717027200"
            status = np_quota_watch.detect_and_schedule(text, "test")
        self.assertEqual(status, "recorded (no at)")
        state = np_quota_watch._load_state()
        self.assertEqual(state["reset_epoch"], 1717027200.0)
        self.assertEqual(state["resume_epoch"], 1717027260.0)
        self.assertFalse(state["notified"])

    def test_same_reset_epoch_is_not_rescheduled(self):
        text = "usage limit reached|1717027200"
        with mock.patch.object(np_quota_watch, "_schedule_at", return_value=True) as scheduled:
            np_quota_watch.detect_and_schedule(text, "test")
            status = np_quota_watch.detect_and_schedule(text, "test")
        self.assertEqual(status, "already scheduled")
        scheduled.assert_called_once()

    def test_notify_now_fires_once(self):
        text = "usage limit reached|1717027200"
        with mock.patch.object(np_quota_watch, "_schedule_at", return_value=False):
            np_quota_watch.detect_and_schedule(text, "test")
        with mock.patch.object(np_quota_watch, "_notify", return_value=True) as notify:
            self.assertEqual(np_quota_watch.notify_now(), "notified")
            self.assertEqual(np_quota_watch.notify_now(), "nothing to notify")
        notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
