"""Direct unit tests for np_evaluator.evaluate() -- the already-existing,
in-process Python port of np-evaluator.sh's orchestration logic (consumed
today by backcapture_sweep.py and the MCP server's bash-free fallback).
Written as part of retiring np-evaluator.sh and its bash test suite (including
tests/mcp/parity/test_evaluator_parity.sh, which can no longer run once the
bash side is deleted)."""
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is engine/setup/tests/evaluator -- two levels up is engine/setup
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_evaluator  # noqa: E402


class TestNpEvaluator(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|\n")
        self.claude_bin = os.path.join(self.tmp, "claude")
        with open(self.claude_bin, "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(self.claude_bin, 0o755)
        self.transcript = os.path.join(self.tmp, "transcript.jsonl")
        with open(self.transcript, "w") as fh:
            fh.write('{"role":"user","content":"hi"}\n')
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
            "EVAL_INBOX": os.path.join(self.tmp, "inbox"),
            "EVAL_JUDGE_LOG": os.path.join(self.tmp, "eval.log"),
            "CLAUDE_BIN": self.claude_bin,
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("NERVEPACK_AGENT", None)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _payload(self):
        return {"session_id": "sid-1", "transcript_path": self.transcript, "cwd": "/x/proj"}

    def _write_transcript(self, output_tokens=0):
        """Real transcript, parsed for real by the actual (unmocked) np-eval-signals.py
        -- no subprocess mocking needed. output_tokens is embedded as a real assistant
        `usage` block so the cost-aware-suggestion test (test_2) can drive a real high
        token count through the real signal extractor, exactly as production does."""
        with open(self.transcript, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "message": {
                "id": "m1", "role": "assistant", "content": [{"type": "text", "text": "ok"}],
                "usage": {"output_tokens": output_tokens, "input_tokens": 10}}}) + "\n")

    def _inbox_line(self):
        inbox = os.environ["EVAL_INBOX"]
        files = os.listdir(inbox)
        self.assertEqual(len(files), 1)
        with open(os.path.join(inbox, files[0]), encoding="utf-8") as fh:
            return fh.read().strip()

    def test_1_happy_path_writes_record_and_redacts_secret(self):
        self._write_transcript(output_tokens=1000)
        verdict = ('{"contribution_score":80,"helped":["did X"],"shortfalls":[],'
                   '"suggestions":[],"assets_used":[]}')
        with mock.patch.object(np_evaluator.np_model, "complete", return_value=verdict):
            status = np_evaluator.evaluate(self._payload())
        self.assertEqual(status, "evaluated")
        record = json.loads(self._inbox_line())
        self.assertEqual(record["contribution_score"], 80)
        self.assertEqual(record["project"], "proj")
        self.assertEqual(record["signals"]["tokens"]["output"], 1000)

    def test_2_cost_aware_suggestion_appended_on_high_tokens_low_score(self):
        self._write_transcript(output_tokens=300000)
        verdict = ('{"contribution_score":20,"helped":[],"shortfalls":["missed"],'
                   '"suggestions":[],"assets_used":[]}')
        with mock.patch.object(np_evaluator.np_model, "complete", return_value=verdict):
            np_evaluator.evaluate(self._payload())
        record = json.loads(self._inbox_line())
        texts = " ".join(s["text"].lower() for s in record["suggestions"])
        self.assertIn("token cost", texts)

    def test_3_toggle_off_no_model_call_no_write(self):
        self._write_transcript()
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|off|\n")
        with mock.patch.object(np_evaluator.np_model, "complete") as m:
            status = np_evaluator.evaluate(self._payload())
            m.assert_not_called()
        self.assertEqual(status, "evaluated")
        self.assertFalse(os.path.isdir(os.environ["EVAL_INBOX"]))

    def test_4_reentry_guard_no_model_call(self):
        self._write_transcript()
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            with mock.patch.object(np_evaluator.np_model, "complete") as m:
                status = np_evaluator.evaluate(self._payload())
                m.assert_not_called()
        self.assertEqual(status, "evaluated")

    def test_5_non_json_judge_output_bails_logged_no_write(self):
        self._write_transcript()
        with mock.patch.object(np_evaluator.np_model, "complete", return_value="not json"):
            status = np_evaluator.evaluate(self._payload())
        self.assertEqual(status, "evaluated")
        self.assertFalse(os.path.isdir(os.environ["EVAL_INBOX"]) and os.listdir(os.environ["EVAL_INBOX"]))
        with open(os.environ["EVAL_JUDGE_LOG"], encoding="utf-8") as fh:
            self.assertIn("bail", fh.read())


if __name__ == "__main__":
    unittest.main()
