#!/usr/bin/env python3
"""#113B: the doctor must be able to see a pipeline that RUNS but does not DRAIN.

The distinguishing case (`test_catches_the_running_but_not_draining_failure`) is
the one that matters: it is green under maintenance-freshness, because the cron
fired on time, and must be a WARN here."""
import os
import sys
import time
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "nervepack_engine"))
sys.path.insert(0, ENGINE)

import np_episodic_freshness as ef  # noqa: E402


def _age(path, days):
    """Backdate a path's mtime by `days`."""
    t = time.time() - days * 86400
    os.utime(path, (t, t))


class TestEpisodicFreshness(unittest.TestCase):
    def setUp(self):
        self._inbox = tempfile.mkdtemp()
        self._content = tempfile.mkdtemp()
        os.makedirs(os.path.join(self._content, "memory", "episodic"))
        self._env = dict(os.environ)
        os.environ["NP_EPISODIC_INBOX"] = self._inbox
        os.environ["NP_CONTENT_DIR"] = self._content

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        for d in (self._inbox, self._content):
            shutil.rmtree(d, ignore_errors=True)

    def _queue(self, name, days_old):
        p = os.path.join(self._inbox, name)
        with open(p, "w") as fh:
            fh.write('{"headline":"x"}\n')
        _age(p, days_old)
        return p

    def _index(self, days_old):
        p = os.path.join(self._content, "memory", "episodic", "INDEX.md")
        with open(p, "w") as fh:
            fh.write("# episodic\n")
        _age(p, days_old)
        return p

    def test_empty_inbox_passes(self):
        self._index(30)          # quiet weeks are not a fault when nothing is queued
        self.assertTrue(ef.report().startswith("PASS"), ef.report())

    def test_work_in_flight_passes(self):
        """A note queued moments ago is normal mid-session, not a broken drain."""
        self._queue("fresh.jsonl", 0)
        self._index(0)
        self.assertTrue(ef.report().startswith("PASS"), ef.report())

    def test_catches_the_running_but_not_draining_failure(self):
        """#113 exactly: notes piled up for a week while the episodic layer stood
        still. The cron was firing the whole time, so maintenance-freshness was
        green — this check is the one that must go red."""
        for i in range(5):
            self._queue("note%d.jsonl" % i, 7)
        self._index(9)
        out = ef.report()
        self.assertTrue(out.startswith("WARN"), out)
        self.assertIn("5 note(s) queued", out)
        self.assertIn("stale", out)

    def test_drained_recently_passes_even_with_a_backlog(self):
        """Old notes are fine if the layer is still moving — that is a slow drain,
        not a dead one, and must not cry wolf."""
        self._queue("old.jsonl", 7)
        self._index(0)
        self.assertTrue(ef.report().startswith("PASS"), ef.report())

    def test_index_never_written_with_queued_work_warns(self):
        self._queue("note.jsonl", 7)      # no INDEX at all
        out = ef.report()
        self.assertTrue(out.startswith("WARN"), out)
        self.assertIn("never written", out)

    def test_missing_inbox_dir_passes(self):
        """Fail-open: a machine that has never captured anything is not broken."""
        shutil.rmtree(self._inbox, ignore_errors=True)
        self.assertTrue(ef.report().startswith("PASS"), ef.report())

    def test_hidden_files_are_not_counted_as_queued_work(self):
        p = os.path.join(self._inbox, ".gitkeep")
        open(p, "w").close()
        _age(p, 30)
        self._index(30)
        self.assertTrue(ef.report().startswith("PASS"), ef.report())

    def test_never_raises(self):
        """Advisory only — a doctor check must not be able to break the doctor, so
        an exception anywhere under report() degrades to PASS rather than escaping."""
        original = ef.survey

        def boom():
            raise RuntimeError("disk fell over")

        ef.survey = boom
        try:
            out = ef.report()
        finally:
            ef.survey = original
        self.assertTrue(out.startswith("PASS"), out)
        self.assertIn("unavailable", out)


class TestDoctorWiring(unittest.TestCase):
    """The module is only useful if the doctor actually dispatches to it."""

    def test_capability_is_registered_and_dispatched(self):
        import json
        caps_path = os.path.normpath(os.path.join(
            HERE, "..", "..", "..", "onboard", "capabilities.json"))
        with open(caps_path) as fh:
            doc = json.load(fh)
        caps = doc["capabilities"] if isinstance(doc, dict) else doc
        ids = [c["id"] for c in caps]
        self.assertIn("episodic-freshness", ids)

        doctor = os.path.join(ENGINE, "np_doctor.py")
        with open(doctor, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('cap_id == "episodic-freshness"', src)
        self.assertIn("np_episodic_freshness.report()", src)


if __name__ == "__main__":
    unittest.main()
