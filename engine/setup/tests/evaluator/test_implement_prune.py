"""np_implement_suggestion.prune: TTL cleanup of status and queue files."""
import json
import os
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
for _p in (_SETUP, os.path.normpath(os.path.join(_SETUP, "..", "nervepack_engine"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_implement_suggestion as imp  # noqa: E402

OLD = time.time() - 40 * 86400


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.status = os.path.join(self.tmp.name, "implement-status")
        self.qdir = os.path.join(self.tmp.name, "implement-queue")
        os.makedirs(self.status)
        os.makedirs(self.qdir)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, d, name, data, age=None):
        path = os.path.join(d, name)
        with open(path, "w") as fh:
            json.dump(data, fh)
        if age is not None:
            os.utime(path, (age, age))
        return path

    def test_old_finished_status_removed_fresh_kept(self):
        old = self.put(self.status, "a" * 16 + ".json", {"state": "done"}, OLD)
        fresh = self.put(self.status, "b" * 16 + ".json", {"state": "failed"})
        self.assertEqual(imp.prune(self.status, self.qdir, ttl_days=30), 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_queued_and_running_status_kept(self):
        q = self.put(self.status, "c" * 16 + ".json", {"state": "queued"}, OLD)
        r = self.put(self.status, "d" * 16 + ".json", {"state": "running"}, OLD)
        imp.prune(self.status, self.qdir, ttl_days=30)
        self.assertTrue(os.path.exists(q))
        self.assertTrue(os.path.exists(r))

    def test_old_queue_entry_removed(self):
        old = self.put(self.qdir, "%020d-%s.json" % (1, "e" * 16), {"key": "e" * 16}, OLD)
        fresh = self.put(self.qdir, "%020d-%s.json" % (2, "f" * 16), {"key": "f" * 16})
        imp.prune(self.status, self.qdir, ttl_days=30)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_running_json_kept_while_pid_alive(self):
        path = self.put(self.qdir, "running.json", {"key": "k", "pid": os.getpid()}, OLD)
        imp.prune(self.status, self.qdir, ttl_days=30)
        self.assertTrue(os.path.exists(path))

    def test_stale_running_json_removed(self):
        path = self.put(self.qdir, "running.json", {"key": "k", "pid": 0}, OLD)
        imp.prune(self.status, self.qdir, ttl_days=30)
        self.assertFalse(os.path.exists(path))

    def test_zero_ttl_disables(self):
        old = self.put(self.status, "a" * 16 + ".json", {"state": "done"}, OLD)
        self.assertEqual(imp.prune(self.status, self.qdir, ttl_days=0), 0)
        self.assertTrue(os.path.exists(old))

    def test_missing_dirs_are_fine(self):
        self.assertEqual(imp.prune("/nonexistent/x", "/nonexistent/y", ttl_days=30), 0)


if __name__ == "__main__":
    unittest.main()
