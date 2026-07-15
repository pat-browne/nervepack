"""Tests for nervepack_engine.hooks.backcapture_sweep — the Python port of
np-backcapture-sweep.sh. Ports every scenario from
engine/setup/tests/episodic/test_backcapture.sh (9 cases) plus one new case
(test_claim_is_atomic) exercising the SEEN_DIR claim race directly. Stub
capture_fn/evaluate_fn are injected instead of shelling to a fake `claude`
binary — this exercises the exact same discover/claim/process control flow
the bash test checked, without needing a model stub."""
import json
import os
import sys
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is engine/setup/tests/nervepack_engine — two levels up is engine/setup
# (needed so backcapture_sweep.py's own `import np_capture` etc. resolve when
# this test imports it directly, bypassing cli.py's own sys.path fixup), three
# levels up is engine/ (needed for `import nervepack_engine`).
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _mktranscript(projects_dir, sid, cwd="/home/test/proj", ago=None):
    d = os.path.join(projects_dir, "proj")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + ".jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        # Compact (no spaces) to match real Claude Code transcript formatting —
        # the cwd-extraction regex in backcapture_sweep.py mirrors the bash
        # original's `grep -oE '"cwd":"[^"]*"'`, which has no tolerance for a
        # space after the colon.
        fh.write(json.dumps({"type": "user", "cwd": cwd,
                              "message": {"role": "user", "content": "hi"}},
                             separators=(",", ":")) + "\n")
        fh.write(json.dumps({"type": "assistant", "message": {
            "id": "m1", "role": "assistant",
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 10, "output_tokens": 20,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}},
                             separators=(",", ":")) + "\n")
    if ago is not None:
        t = time.time() - ago
        os.utime(path, (t, t))
    return path


class _Env(unittest.TestCase):
    """Shared per-test hermetic environment, mirroring the bash test's tmp dir + env exports."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmp, "projects")
        self.seen_dir = os.path.join(self.tmp, "bc-seen")
        self.queue_dir = os.path.join(self.tmp, "bc-queue")
        self.metrics = os.path.join(self.tmp, "metrics.jsonl")
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        self.toggles_local = os.path.join(self.tmp, "local")
        with open(self.toggles_conf, "w") as fh:
            fh.write("memory|shared|runtime|on|\n")
        self._env_patch = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": self.toggles_local,
            "CLAUDE_PROJECTS_DIR": self.projects_dir,
            "BACKCAPTURE_SEEN_DIR": self.seen_dir,
            "BACKCAPTURE_QUEUE_DIR": self.queue_dir,
            "BACKCAPTURE_METRICS": self.metrics,
            "BACKCAPTURE_MIN_AGE_SEC": "120",
            "BACKCAPTURE_LOG": os.path.join(self.tmp, "bc.log"),
        })
        self._env_patch.start()
        os.environ.pop("NERVEPACK_AGENT", None)
        self.addCleanup(self._env_patch.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, sid_payload="none"):
        from nervepack_engine.hooks import backcapture_sweep
        captured, evaluated = [], []
        backcapture_sweep.run(
            json.dumps({"session_id": sid_payload}),
            capture_fn=lambda payload, mode: captured.append((payload, mode)),
            evaluate_fn=lambda payload: evaluated.append(payload),
        )
        return captured, evaluated


class TestBackcaptureSweep(_Env):
    def test_1_settled_uncaptured_session_is_captured(self):
        _mktranscript(self.projects_dir, "11111111-old", ago=600)
        captured, evaluated = self._run(sid_payload="22222222-active")
        self.assertEqual(len(captured), 1)
        self.assertEqual(len(evaluated), 1)
        self.assertEqual(captured[0][0]["session_id"], "11111111-old")
        self.assertEqual(captured[0][0]["cwd"], "/home/test/proj")
        self.assertEqual(captured[0][1], "session-end")

    def test_2_active_too_new_session_skipped(self):
        _mktranscript(self.projects_dir, "22222222-active")  # just written, no ago=
        captured, _ = self._run(sid_payload="22222222-active")
        self.assertEqual(captured, [])
        self.assertFalse(os.path.exists(os.path.join(self.seen_dir, "22222222-active")))

    def test_3_already_in_metrics_skipped_but_marked_seen(self):
        _mktranscript(self.projects_dir, "33333333-done", ago=600)
        with open(self.metrics, "w") as fh:
            fh.write(json.dumps({"session_id": "33333333-done"}) + "\n")
        captured, _ = self._run()
        self.assertEqual(captured, [])
        self.assertTrue(os.path.exists(os.path.join(self.seen_dir, "33333333-done")))

    def test_3b_subagent_transcript_never_captured(self):
        _mktranscript(self.projects_dir, "agent-44444444", ago=600)
        captured, _ = self._run()
        self.assertEqual(captured, [])

    def test_4_idempotent_second_sweep_adds_nothing(self):
        _mktranscript(self.projects_dir, "11111111-old", ago=600)
        self._run()
        captured, evaluated = self._run()
        self.assertEqual(len(captured), 0)
        self.assertEqual(len(evaluated), 0)

    def test_5_toggle_off_no_work(self):
        with open(self.toggles_local, "w") as fh:
            fh.write("memory.backcapture=off\n")
        _mktranscript(self.projects_dir, "11111111-old", ago=600)
        captured, evaluated = self._run()
        self.assertEqual(captured, [])
        self.assertEqual(evaluated, [])
        self.assertFalse(os.path.isdir(self.queue_dir))

    def test_6_backlog_queues_all_processes_capped_oldest_first(self):
        with open(self.toggles_local, "w") as fh:
            fh.write("memory.backcapture_max=1\n")
        _mktranscript(self.projects_dir, "55555555-older", ago=1000)
        _mktranscript(self.projects_dir, "66666666-newer", ago=500)
        captured, _ = self._run()
        self.assertTrue(os.path.isdir(self.queue_dir))
        self.assertTrue(os.path.exists(os.path.join(self.queue_dir, "55555555-older")))
        self.assertTrue(os.path.exists(os.path.join(self.queue_dir, "66666666-newer")))
        self.assertTrue(os.path.exists(os.path.join(self.seen_dir, "55555555-older")))
        self.assertFalse(os.path.exists(os.path.join(self.seen_dir, "66666666-newer")))
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0]["session_id"], "55555555-older")
        # next sweep drains the deferred backlog item
        captured2, _ = self._run()
        self.assertTrue(os.path.exists(os.path.join(self.seen_dir, "66666666-newer")))
        self.assertEqual(len(captured2), 1)
        self.assertEqual(captured2[0][0]["session_id"], "66666666-newer")

    def test_7_prequeued_session_processed_after_aging_past_window(self):
        with open(self.toggles_local, "w") as fh:
            fh.write("memory.backcapture_max=5\n")
        stale_path = _mktranscript(self.projects_dir, "77777777-stale", ago=700000)
        os.makedirs(self.queue_dir, exist_ok=True)
        stale_mt = time.time() - 700000
        with open(os.path.join(self.queue_dir, "77777777-stale"), "w") as fh:
            json.dump({"sid": "77777777-stale", "mtime": stale_mt,
                       "transcript_path": stale_path, "cwd": "/home/test/proj"}, fh)
        captured, _ = self._run()
        self.assertTrue(os.path.exists(os.path.join(self.seen_dir, "77777777-stale")))
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0]["session_id"], "77777777-stale")

    def test_8_never_queues_session_already_too_old_on_first_sighting(self):
        with open(self.toggles_local, "w") as fh:
            fh.write("memory.backcapture_max=5\n")
        _mktranscript(self.projects_dir, "99999999-toolold", ago=700000)
        captured, _ = self._run()
        self.assertFalse(os.path.exists(os.path.join(self.queue_dir, "99999999-toolold")))
        self.assertFalse(os.path.exists(os.path.join(self.seen_dir, "99999999-toolold")))
        self.assertEqual(captured, [])

    def test_9_nervepack_agent_guard_skips_entire_sweep(self):
        _mktranscript(self.projects_dir, "11111111-old", ago=600)
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            captured, _ = self._run()
        self.assertEqual(captured, [])
        self.assertFalse(os.path.isdir(self.queue_dir))

    def test_10_claim_is_atomic_pre_existing_marker_blocks_processing(self):
        """New case beyond the ported 9: a queue entry whose SEEN marker already
        exists (e.g. claimed by a concurrent sweep) is never (re)processed, even
        though it's still sitting in the queue dir."""
        path = _mktranscript(self.projects_dir, "aaaaaaaa-claimed", ago=600)
        os.makedirs(self.queue_dir, exist_ok=True)
        os.makedirs(self.seen_dir, exist_ok=True)
        mt = time.time() - 600
        with open(os.path.join(self.queue_dir, "aaaaaaaa-claimed"), "w") as fh:
            json.dump({"sid": "aaaaaaaa-claimed", "mtime": mt,
                       "transcript_path": path, "cwd": "/home/test/proj"}, fh)
        open(os.path.join(self.seen_dir, "aaaaaaaa-claimed"), "a").close()
        captured, _ = self._run()
        self.assertEqual(captured, [])


if __name__ == "__main__":
    unittest.main()
