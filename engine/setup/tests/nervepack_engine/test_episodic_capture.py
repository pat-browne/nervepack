"""Tests for nervepack_engine.hooks.episodic_capture -- the thin cli.py-dispatched
wrapper around the already-existing, already-tested np_capture.capture(). Mirrors
backcapture_sweep.py's capture_fn-injection pattern. Does NOT re-test capture()'s
own orchestration logic (see test_np_capture.py for that) -- only the wrapper's
own responsibilities: payload parsing, mode forwarding, fail-open on a raising
capture_fn, and the always-empty-string return (this hook never writes to
stdout, matching the bash original)."""
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestEpisodicCapture(unittest.TestCase):
    def _run(self, payload_dict, mode="session-end", capture_fn=None):
        from nervepack_engine.hooks import episodic_capture
        return episodic_capture.run(json.dumps(payload_dict), mode, capture_fn)

    def test_1_forwards_parsed_payload_and_mode(self):
        calls = []
        out = self._run({"session_id": "s1"}, mode="checkpoint",
                         capture_fn=lambda payload, mode: calls.append((payload, mode)))
        self.assertEqual(out, "")
        self.assertEqual(calls, [({"session_id": "s1"}, "checkpoint")])

    def test_2_default_mode_is_session_end(self):
        calls = []
        out = self._run({}, capture_fn=lambda payload, mode: calls.append(mode))
        self.assertEqual(out, "")
        self.assertEqual(calls, ["session-end"])

    def test_3_capture_fn_exception_fails_open(self):
        def _boom(payload, mode):
            raise RuntimeError("boom")
        out = self._run({}, capture_fn=_boom)
        self.assertEqual(out, "")

    def test_4_malformed_payload_json_fails_open(self):
        from nervepack_engine.hooks import episodic_capture
        calls = []
        out = episodic_capture.run("not json", "session-end",
                                    lambda payload, mode: calls.append(payload))
        self.assertEqual(out, "")
        self.assertEqual(calls, [{}])

    def test_5_default_capture_fn_is_real_np_capture(self):
        from nervepack_engine.hooks import episodic_capture
        import np_capture
        with mock.patch.object(np_capture, "capture", return_value="captured") as m:
            out = episodic_capture.run("{}", "session-end")
            m.assert_called_once_with({}, "session-end")
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
