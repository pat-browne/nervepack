# np-test: job-health | job list from the scheduler table, installed/toggle/last-run/status/overdue per job
"""np_job_health reports every scheduled nervepack job in one table. The job
list comes from np_scheduler_install, plus any extra com.nervepack.* launchd
agent found on disk. Every OS call goes through a seam, so these run anywhere."""
import datetime
import os
import plistlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.normpath(os.path.join(SETUP, "..", "nervepack_engine"))
for _p in (SETUP, ENGINE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_job_health as jh  # noqa: E402
import np_scheduler_install  # noqa: E402


def _stamp(hours_ago):
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.la = os.path.join(self.tmp, "LaunchAgents")
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.la)
        os.makedirs(self.logs)
        self.enabled = mock.patch.object(jh.np_toggle, "enabled", return_value=True)
        self.enabled.start()
        self.addCleanup(self.enabled.stop)

    def survey(self, backend="launchd", exits=None, crontab=""):
        return {r["name"]: r for r in jh.survey(
            backend=backend, la_dir=self.la, log_dir=self.logs,
            launchctl_fn=lambda: dict(exits or {}), crontab_fn=lambda: crontab,
            schtasks_fn=lambda name: False)}


class JobListTest(Base):
    def test_jobs_come_from_scheduler_table(self):
        names = [j[0] for j in np_scheduler_install._JOBS]
        self.assertEqual([j["name"] for j in jh.managed_jobs()], names)

    def test_every_scheduled_job_has_a_toggle(self):
        for name, *_ in np_scheduler_install._JOBS:
            self.assertIn(name, np_scheduler_install.JOB_TOGGLES)

    def test_weekly_cadence_is_seven_days(self):
        cad = {j["name"]: j["cadence_s"] for j in jh.managed_jobs()}
        self.assertEqual(cad["compact"], 7 * 86400)
        self.assertEqual(cad["memory-promote"], 86400)

    def test_unmanaged_launchd_agent_is_discovered(self):
        with open(os.path.join(self.la, "com.nervepack.ado-status-sync.plist"), "wb") as fh:
            plistlib.dump({"Label": "com.nervepack.ado-status-sync", "StartInterval": 3600}, fh)
        rows = self.survey()
        self.assertIn("ado-status-sync", rows)
        self.assertEqual(rows["ado-status-sync"]["cadence_s"], 3600)
        self.assertFalse(rows["ado-status-sync"]["managed"])


class RowTest(Base):
    def _plist(self, name):
        _write(os.path.join(self.la, "com.nervepack.%s.plist" % name), "<plist/>")

    def test_healthy_job(self):
        self._plist("compact")
        _write(os.path.join(self.logs, "compact.log"),
               "%s === compact run ===\nok: agent run completed\n" % _stamp(24))
        r = self.survey(exits={"com.nervepack.compact": 0})["compact"]
        self.assertTrue(r["installed"])
        self.assertTrue(r["enabled"])
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["exit"], 0)
        self.assertFalse(r["overdue"])

    def test_error_in_last_run_only(self):
        _write(os.path.join(self.logs, "refine.log"),
               "%s === refine run ===\nERROR: old\n%s === refine run ===\nok: agent run completed\n"
               % (_stamp(200), _stamp(1)))
        _write(os.path.join(self.logs, "memory-promote.log"),
               "%s === memory-promote run ===\n%s ERROR: agent run exited non-zero\n"
               % (_stamp(1), _stamp(1)))
        rows = self.survey()
        self.assertEqual(rows["refine"]["status"], "ok")
        self.assertEqual(rows["memory-promote"]["status"], "error")

    def test_unpublished_is_warn(self):
        _write(os.path.join(self.logs, "aggregate-metrics.log"),
               "aggregated (NOT PUBLISHED: refused: overlay is on 'feat/x', not 'main'.)\n")
        self.assertEqual(self.survey()["aggregate-metrics"]["status"], "warn")

    def test_overdue_and_never_ran(self):
        _write(os.path.join(self.logs, "skill-maintain.log"), "%s done\n" % _stamp(24 * 5))
        rows = self.survey()
        self.assertTrue(rows["skill-maintain"]["overdue"])
        self.assertIsNone(rows["episodic-maintain"]["last_run"])
        self.assertTrue(rows["episodic-maintain"]["overdue"])
        self.assertFalse(rows["episodic-maintain"]["installed"])

    def test_disabled_job_is_never_overdue(self):
        self.enabled.stop()
        with mock.patch.object(jh.np_toggle, "enabled", return_value=False):
            r = self.survey()["compact"]
        self.enabled.start()
        self.assertFalse(r["enabled"])
        self.assertFalse(r["overdue"])

    def test_cron_backend_reads_crontab(self):
        rows = self.survey(backend="cron", crontab="0 10 * * 3 python3 cli.py cron compact # nervepack-compact\n")
        self.assertTrue(rows["compact"]["installed"])
        self.assertFalse(rows["refine"]["installed"])

    def test_unknown_backend_degrades(self):
        r = self.survey(backend="none")["compact"]
        self.assertIsNone(r["installed"])


class ReportTest(Base):
    def test_report_warns_on_problem_jobs(self):
        with mock.patch.object(jh, "survey", return_value=[
                {"name": "a", "enabled": True, "installed": True, "status": "ok", "overdue": False, "exit": 0},
                {"name": "b", "enabled": True, "installed": False, "status": "unknown", "overdue": True, "exit": None}]):
            line = jh.report()
        self.assertTrue(line.startswith("WARN"))
        self.assertIn("b", line)
        self.assertNotIn("a:", line)

    def test_report_passes_when_all_healthy(self):
        with mock.patch.object(jh, "survey", return_value=[
                {"name": "a", "enabled": True, "installed": True, "status": "ok", "overdue": False, "exit": 0}]):
            self.assertTrue(jh.report().startswith("PASS"))

    def test_report_respects_toggle(self):
        self.enabled.stop()
        with mock.patch.object(jh.np_toggle, "enabled", return_value=False):
            self.assertIn("disabled", jh.report())
        self.enabled.start()

    def test_report_never_raises(self):
        with mock.patch.object(jh, "survey", side_effect=RuntimeError("boom")):
            self.assertTrue(jh.report().startswith("PASS"))


if __name__ == "__main__":
    unittest.main()
