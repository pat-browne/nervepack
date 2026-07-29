# np-test: maintenance-freshness | last-run parsing, staleness classification,
#          toggle gating, and the doctor check's PASS/WARN wording.
"""The alarm that would have caught the 2026-07 incident on day 2.

Three separate failures each left the maintenance crons doing nothing while
every surface still looked healthy:
  * the host suspended across the cron window, so jobs never fired at all;
  * memory-promote read the wrong dir and reported "nothing to promote" forever;
  * headless auth expired and every model call failed (#201).
None of them changed anything a human looks at. This module answers one
question -- "when did each maintenance job last actually run?" -- so any of the
three shows up as a stale job.
"""
import datetime
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.abspath(os.path.join(HERE, "..", ".."))          # engine/setup
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "nervepack_engine"))
for p in (SETUP, ENGINE):
    if p not in sys.path:
        sys.path.insert(0, p)

import np_maintenance_freshness as mf  # noqa: E402


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _stamp(days_ago):
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class LastRunParsingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _log(self, body):
        p = os.path.join(self.tmp, "x.log")
        _write(p, body)
        return p

    def test_leading_timestamp_form(self):
        p = self._log("2026-07-29T14:56:49Z === memory-promote run ===\n")
        self.assertEqual(mf.last_run(p), "2026-07-29T14:56:49Z")

    def test_embedded_timestamp_form(self):
        # The older bash bodies wrote the stamp *inside* the header.
        p = self._log("=== 2026-07-22T14:00:01Z memory-promote run ===\n")
        self.assertEqual(mf.last_run(p), "2026-07-22T14:00:01Z")

    def test_last_header_wins_not_last_line(self):
        p = self._log(
            "2026-07-01T00:00:00Z === memory-promote run ===\n"
            "2026-07-20T00:00:00Z === memory-promote run ===\n"
            "some trailing agent report text with no stamp\n")
        self.assertEqual(mf.last_run(p), "2026-07-20T00:00:00Z")

    def test_missing_log_returns_none(self):
        self.assertIsNone(mf.last_run(os.path.join(self.tmp, "nope.log")))

    def test_log_with_no_stamp_at_all_returns_none(self):
        p = self._log("just some output\nno run header here\n")
        self.assertIsNone(mf.last_run(p))

    def test_headerless_log_falls_back_to_newest_stamp(self):
        # skill-maintain (np_skill_maintain) writes stamped result lines and no
        # run header. Treating that as "never ran" is a false alarm on a healthy
        # job, which is worse than no check at all.
        p = self._log(
            "2026-07-26T15:15:01Z architecture-freshness: 0 gap(s)\n"
            "2026-07-27T15:15:01Z architecture-freshness: 0 gap(s)\n"
            "2026-07-27T15:15:01Z no skills over split threshold (8KB)\n")
        self.assertEqual(mf.last_run(p), "2026-07-27T15:15:01Z")

    def test_header_wins_over_a_later_bare_stamp(self):
        # Agent output is appended after the header (#203). A stamp inside that
        # output must not be mistaken for a newer run.
        p = self._log(
            "2026-07-20T00:00:00Z === memory-promote run ===\n"
            "report mentioning 2026-07-25T00:00:00Z in passing\n")
        self.assertEqual(mf.last_run(p), "2026-07-20T00:00:00Z")


class StalenessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, ".cache", "nervepack")
        os.makedirs(self.cache)
        self.env = mock.patch.dict(os.environ, {"HOME": self.tmp})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job_log(self, basename, days_ago):
        _write(os.path.join(self.cache, basename),
               "%s === run ===\n" % _stamp(days_ago))

    def _all_enabled(self, _key):
        return True

    def test_fresh_daily_job_not_stale(self):
        self._job_log("memory-promote.log", 0)
        with mock.patch.object(mf.np_toggle, "enabled", side_effect=self._all_enabled):
            rows = {r.name: r for r in mf.survey()}
        self.assertFalse(rows["memory-promote"].stale)

    def test_daily_job_past_cadence_plus_grace_is_stale(self):
        # daily cadence (1d) + default grace (2d) => 3d is the boundary; 5d is stale.
        self._job_log("memory-promote.log", 5)
        with mock.patch.object(mf.np_toggle, "enabled", side_effect=self._all_enabled):
            rows = {r.name: r for r in mf.survey()}
        self.assertTrue(rows["memory-promote"].stale)
        self.assertGreaterEqual(rows["memory-promote"].age_days, 5)

    def test_weekly_job_at_five_days_not_stale(self):
        # refine is weekly -- 5 days must NOT trip it, or the check cries wolf.
        self._job_log("refine.log", 5)
        with mock.patch.object(mf.np_toggle, "enabled", side_effect=self._all_enabled):
            rows = {r.name: r for r in mf.survey()}
        self.assertFalse(rows["refine"].stale)

    def test_weekly_job_past_cadence_plus_grace_is_stale(self):
        self._job_log("refine.log", 12)
        with mock.patch.object(mf.np_toggle, "enabled", side_effect=self._all_enabled):
            rows = {r.name: r for r in mf.survey()}
        self.assertTrue(rows["refine"].stale)

    def test_never_run_is_stale_with_none_age(self):
        with mock.patch.object(mf.np_toggle, "enabled", side_effect=self._all_enabled):
            rows = {r.name: r for r in mf.survey()}
        self.assertTrue(rows["memory-promote"].stale)
        self.assertIsNone(rows["memory-promote"].age_days)

    def test_disabled_job_is_skipped_entirely(self):
        # A toggled-off feature is not a fault -- it must not appear as stale.
        def _only_memory_off(key):
            return not key.startswith("memory")

        with mock.patch.object(mf.np_toggle, "enabled", side_effect=_only_memory_off):
            names = [r.name for r in mf.survey()]
        self.assertNotIn("memory-promote", names)
        self.assertNotIn("episodic-maintain", names)
        self.assertIn("refine", names)

    def test_grace_is_toggle_param_driven(self):
        self._job_log("memory-promote.log", 5)
        with mock.patch.object(mf.np_toggle, "enabled", side_effect=self._all_enabled), \
             mock.patch.object(mf.np_toggle, "param", return_value="30"):
            rows = {r.name: r for r in mf.survey()}
        self.assertFalse(rows["memory-promote"].stale)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".cache", "nervepack"))
        self.env = mock.patch.dict(os.environ, {"HOME": self.tmp})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_fresh_reports_pass(self):
        for base in ("memory-promote.log", "episodic-maintain.log", "skill-maintain.log",
                     "refine.log", "compact.log"):
            _write(os.path.join(self.tmp, ".cache", "nervepack", base),
                   "%s === run ===\n" % _stamp(0))
        with mock.patch.object(mf.np_toggle, "enabled", return_value=True):
            self.assertTrue(mf.report().startswith("PASS"))

    def test_stale_job_reports_warn_naming_the_job(self):
        _write(os.path.join(self.tmp, ".cache", "nervepack", "memory-promote.log"),
               "%s === run ===\n" % _stamp(9))
        with mock.patch.object(mf.np_toggle, "enabled", return_value=True):
            out = mf.report()
        self.assertTrue(out.startswith("WARN"))
        self.assertIn("memory-promote", out)

    def test_report_never_raises_on_unreadable_cache(self):
        # invariant 1: an advisory check must never break the doctor.
        with mock.patch.object(mf, "_cache_dir", side_effect=OSError("boom")), \
             mock.patch.object(mf.np_toggle, "enabled", return_value=True):
            self.assertIsInstance(mf.report(), str)


if __name__ == "__main__":
    unittest.main()
