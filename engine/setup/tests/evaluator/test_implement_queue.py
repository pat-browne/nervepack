"""np_implement_suggestion queue: enqueue, dedupe, FIFO drain, continue on
failure, and the post-release re-check that closes the enqueue race."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
for _p in (_SETUP, os.path.normpath(os.path.join(_SETUP, "..", "nervepack_engine"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_implement_suggestion as imp  # noqa: E402


class QueueBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.status = os.path.join(d, "implement-status")
        self.lock = os.path.join(d, "implement.lock")
        self.qdir = imp.queue_dir(self.status)
        conf = os.path.join(d, "toggles.conf")
        with open(conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|implement=on\n")
        self.env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": conf, "NP_TOGGLES_LOCAL": os.path.join(d, "local"),
            "IMPLEMENT_LOG": os.path.join(d, "impl.log")})
        self.env.start()
        os.environ.pop("NERVEPACK_AGENT", None)
        os.environ.pop("IMPLEMENT_QUEUE_DIR", None)
        self.ran = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def status_of(self, text):
        try:
            with open(os.path.join(self.status, imp._status_key(text) + ".json")) as fh:
                return json.load(fh)
        except OSError:
            return {}

    def fake_run(self, fail=()):
        def run(text, edited, target, ctx):
            self.ran.append(text)
            if text in fail:
                raise RuntimeError("boom")
            imp._write_status(ctx["status_dir"], imp._status_key(text), "done")
        return run

    def call(self, text):
        return imp.implement(text, lock_path=self.lock, status_dir=self.status)

    def hold_lock(self):
        os.mkdir(self.lock)
        with open(os.path.join(self.lock, "pid"), "w") as fh:
            fh.write(str(os.getpid()))          # this test process: alive


class TestEnqueue(QueueBase):
    def test_queue_dir_is_a_sibling_of_the_status_dir(self):
        self.assertEqual(os.path.dirname(self.qdir), os.path.dirname(self.status))

    def test_enqueue_writes_entry_and_queued_status(self):
        self.assertTrue(imp.enqueue(self.qdir, self.status, "a", "a2", "hooks"))
        entries = imp.queue_entries(self.qdir)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1]["edited"], "a2")
        self.assertEqual(entries[0][1]["target"], "hooks")
        self.assertIn("enqueued_at", entries[0][1])
        st = self.status_of("a")
        self.assertEqual((st["state"], st["position"]), ("queued", 1))

    def test_duplicate_enqueue_is_a_no_op(self):
        imp.enqueue(self.qdir, self.status, "a")
        self.assertFalse(imp.enqueue(self.qdir, self.status, "a"))
        self.assertEqual(len(imp.queue_entries(self.qdir)), 1)

    def test_enqueue_skips_the_live_running_job(self):
        imp._set_running(self.qdir, imp._status_key("a"), "a")
        self.assertFalse(imp.enqueue(self.qdir, self.status, "a"))

    def test_stale_running_marker_does_not_block(self):
        os.makedirs(self.qdir, exist_ok=True)
        with open(os.path.join(self.qdir, "running.json"), "w") as fh:
            json.dump({"key": imp._status_key("a"), "pid": 2 ** 22 + 12345}, fh)
        self.assertTrue(imp.enqueue(self.qdir, self.status, "a"))

    def test_positions_are_fifo(self):
        for t in ("a", "b", "c"):
            imp.enqueue(self.qdir, self.status, t)
        self.assertEqual(imp.queue_position(self.qdir, imp._status_key("c")), 3)
        self.assertEqual([e["text"] for _, e in imp.queue_entries(self.qdir)], ["a", "b", "c"])


class TestDrain(QueueBase):
    def test_lock_held_enqueues_and_returns(self):
        self.hold_lock()
        with mock.patch.object(imp, "_run_one", self.fake_run()):
            self.assertEqual(self.call("x"), 0)
        self.assertEqual(self.ran, [])
        self.assertEqual(self.status_of("x")["state"], "queued")
        self.assertEqual(len(imp.queue_entries(self.qdir)), 1)

    def test_holder_drains_queue_in_fifo_order(self):
        imp.enqueue(self.qdir, self.status, "b")
        imp.enqueue(self.qdir, self.status, "c")
        with mock.patch.object(imp, "_run_one", self.fake_run()):
            self.call("a")
        self.assertEqual(self.ran, ["a", "b", "c"])
        self.assertEqual(imp.queue_entries(self.qdir), [])
        self.assertFalse(os.path.exists(self.lock))
        self.assertFalse(os.path.exists(os.path.join(self.qdir, "running.json")))

    def test_failed_job_is_marked_and_drain_continues(self):
        imp.enqueue(self.qdir, self.status, "b")
        imp.enqueue(self.qdir, self.status, "c")
        with mock.patch.object(imp, "_run_one", self.fake_run(fail=("b",))):
            self.call("a")
        self.assertEqual(self.ran, ["a", "b", "c"])
        self.assertEqual(self.status_of("b")["state"], "failed")
        self.assertIn("boom", self.status_of("b")["ref"])
        self.assertEqual(self.status_of("c")["state"], "done")

    def test_first_job_already_queued_runs_once(self):
        imp.enqueue(self.qdir, self.status, "a")
        with mock.patch.object(imp, "_run_one", self.fake_run()):
            self.call("a")
        self.assertEqual(self.ran, ["a"])

    def test_entry_added_during_release_is_drained(self):
        """An enqueue landing between the last pop and the lock release."""
        real_clear = imp._clear_running
        added = []

        def clear_and_enqueue(qdir):
            real_clear(qdir)
            if not added:
                added.append(1)
                imp.enqueue(qdir, self.status, "late")
        with mock.patch.object(imp, "_run_one", self.fake_run()), \
                mock.patch.object(imp, "_clear_running", clear_and_enqueue):
            self.call("a")
        self.assertEqual(self.ran, ["a", "late"])
        self.assertEqual(imp.queue_entries(self.qdir), [])

    def test_enqueuer_takes_over_when_holder_released_meanwhile(self):
        """The holder released between our failed claim and our enqueue."""
        calls = []
        real = imp._acquire_lock

        def acquire(path):
            calls.append(path)
            return False if len(calls) == 1 else real(path)
        with mock.patch.object(imp, "_run_one", self.fake_run()), \
                mock.patch.object(imp, "_acquire_lock", acquire):
            self.call("x")
        self.assertEqual(self.ran, ["x"])
        self.assertEqual(imp.queue_entries(self.qdir), [])


if __name__ == "__main__":
    unittest.main()
