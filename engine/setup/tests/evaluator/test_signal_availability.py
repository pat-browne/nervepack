# np-test: signal-availability | signals_present flag + the judge's
#          "telemetry unavailable" instruction, so a missing marker file is not
#          scored as "Nervepack sat idle".
"""The evaluator's hook-fire signals (recall_injections, playbook_fires) come
from a fire-time marker at ~/.cache/nervepack/session-signals/<sid>.log.
count_markers() fails open to all-zeros when that file is absent -- which makes
"we have no telemetry for this session" indistinguishable from "nervepack did
nothing". The judge reads the zeros as evidence of inaction and scores
accordingly.

Measured on 712 real records (2026-07-29). Substantive sessions, >=10 tool calls,
split only on whether the marker file exists:

    marker present : avg score 62.2 (pre-Jul) / 53.6 (Jul+), recall>0 in 98-100%
    marker missing : avg score 31.9 (pre-Jul) / 29.7 (Jul+), recall>0 in 0-5%

A ~25-point penalty on identical-quality work, purely from absent telemetry. The
marker dir is machine-local and never synced, while metrics.jsonl is committed
and shared, so every record evaluated on another machine lands in the shared
series with its signals zeroed.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SIG = os.path.join(HERE, "..", "..", "np-eval-signals.py")
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "nervepack_engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def run_signals(sid, signal_dir, transcript=""):
    env = dict(os.environ)
    env["NP_SIGNAL_DIR"] = signal_dir
    r = subprocess.run([sys.executable, SIG, sid, transcript],
                       capture_output=True, text=True, env=env)
    return json.loads(r.stdout or "{}")


class SignalsPresentFlagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def test_marker_present_reports_signals_present_true(self):
        with open(os.path.join(self.tmp, "s1.log"), "w", encoding="utf-8") as fh:
            fh.write("lesson-recall\nepisodic-recall\n")
        rec = run_signals("s1", self.tmp)
        self.assertTrue(rec["signals_present"])
        self.assertEqual(rec["recall_injections"], 2)

    def test_marker_absent_reports_signals_present_false(self):
        rec = run_signals("nosuchsession", self.tmp)
        self.assertFalse(rec["signals_present"],
                         "absent telemetry must be distinguishable from zero telemetry")
        self.assertEqual(rec["recall_injections"], 0)

    def test_empty_marker_is_present_but_zero(self):
        """A session whose hooks genuinely never fired: the file exists and is
        empty. That IS evidence of inaction and must stay scoreable as such."""
        open(os.path.join(self.tmp, "s2.log"), "w").close()
        rec = run_signals("s2", self.tmp)
        self.assertTrue(rec["signals_present"])
        self.assertEqual(rec["recall_injections"], 0)


class JudgePromptTest(unittest.TestCase):
    """The flag only matters if it reaches the judge."""

    def _tail(self, signals_json):
        import np_evaluator
        return np_evaluator._prompt_tail(signals_json)

    def test_absent_telemetry_adds_an_explicit_caveat(self):
        tail = self._tail(json.dumps({"signals_present": False, "recall_injections": 0}))
        low = tail.lower()
        self.assertIn("unavailable", low)
        self.assertTrue("do not" in low or "must not" in low,
                        "the judge needs an explicit instruction, not just a flag")

    def test_present_telemetry_adds_no_caveat(self):
        tail = self._tail(json.dumps({"signals_present": True, "recall_injections": 3}))
        self.assertNotIn("unavailable", tail.lower())

    def test_malformed_signals_json_does_not_raise(self):
        # fail-open: the evaluator already tolerates "{}" / junk here.
        for bad in ("{}", "not json", ""):
            self.assertIsInstance(self._tail(bad), str)

    def test_legacy_record_without_the_key_is_treated_as_present(self):
        """Historical records predate the flag. Treat absent-key as present so
        we never retroactively caveat the whole committed series."""
        tail = self._tail(json.dumps({"recall_injections": 2}))
        self.assertNotIn("unavailable", tail.lower())


if __name__ == "__main__":
    unittest.main()
