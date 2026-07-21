"""Tests for nervepack_engine.hooks.evaluator -- the thin cli.py-dispatched
wrapper around the already-existing, already-tested np_evaluator.evaluate().
Mirrors backcapture_sweep.py's evaluate_fn-injection pattern. Does NOT re-test
evaluate()'s own orchestration logic (see test_np_evaluator.py for that) --
only the wrapper's own responsibilities."""
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


class TestEvaluatorHook(unittest.TestCase):
    def _run(self, payload_dict, evaluate_fn=None):
        from nervepack_engine.hooks import evaluator
        return evaluator.run(json.dumps(payload_dict), evaluate_fn)

    def test_1_forwards_parsed_payload(self):
        calls = []
        out = self._run({"session_id": "s1"}, evaluate_fn=lambda payload: calls.append(payload))
        self.assertEqual(out, "")
        self.assertEqual(calls, [{"session_id": "s1"}])

    def test_2_evaluate_fn_exception_fails_open(self):
        def _boom(payload):
            raise RuntimeError("boom")
        out = self._run({}, evaluate_fn=_boom)
        self.assertEqual(out, "")

    def test_3_malformed_payload_json_fails_open(self):
        from nervepack_engine.hooks import evaluator
        calls = []
        out = evaluator.run("not json", lambda payload: calls.append(payload))
        self.assertEqual(out, "")
        self.assertEqual(calls, [{}])

    def test_4_default_evaluate_fn_is_real_np_evaluator(self):
        from nervepack_engine.hooks import evaluator
        import np_evaluator
        with mock.patch.object(np_evaluator, "evaluate", return_value="evaluated") as m:
            out = evaluator.run("{}")
            m.assert_called_once_with({})
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
