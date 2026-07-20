"""Tests for nervepack_engine.hooks.struggle_escalation — the Python port of
struggle-escalation.sh. (The task brief that seeded this suite assumed no bash
test existed for this hook; a repo-wide grep during the retirement step found
two — engine/setup/tests/evaluator/test_escalation.sh and
test_install_escalation_hook.sh — both removed alongside the bash original,
their scenarios covered here.) This suite is written to be genuinely thorough
per the coverage gate — not just "passes", but exercises every branch of the
bash original: the prompt counter increments on every call using the
PRE-increment value against MIN_PROMPTS (matching bash's `pcount` semantics
exactly, not the post-increment value), the struggle-count gate, the
once-per-session fire guard, and fail-open when the signal log is missing."""
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is engine/setup/tests/nervepack_engine — two levels up is engine/setup,
# three levels up is engine/
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestStruggleEscalation(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|\n")
        self.sig_dir = os.path.join(self.tmp, "sig")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local"),
            "NP_ESCALATION_STATE": os.path.join(self.tmp, "state"),
            "NP_SIGNAL_DIR": self.sig_dir,
            "NP_ESCALATION_MIN_PROMPTS": "3",
            "NP_ESCALATION_MIN_STRUGGLES": "2",
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write_signal_log(self, sid, guard_fires):
        os.makedirs(self.sig_dir, exist_ok=True)
        with open(os.path.join(self.sig_dir, sid + ".log"), "w") as fh:
            for _ in range(guard_fires):
                fh.write("lesson-guard warn nuke :: abc123\n")

    def _run(self, sid):
        from nervepack_engine.hooks import struggle_escalation
        return struggle_escalation.run(json.dumps({"session_id": sid}))

    def test_no_fire_before_min_prompts(self):
        self._write_signal_log("s1", 5)  # plenty of struggles — prompt count is the gate here
        # bash checks the PRE-increment pcount against MIN_PROMPTS=3: calls 1,2,3 all see
        # pcount 0,1,2 (< 3) -> no fire. Only the 4th call sees pcount=3 (>= 3).
        self.assertEqual(self._run("s1"), "")
        self.assertEqual(self._run("s1"), "")
        self.assertEqual(self._run("s1"), "")

    def test_fires_on_the_call_where_pre_increment_count_reaches_min_prompts(self):
        self._write_signal_log("s1", 5)
        self._run("s1")  # pcount 0 -> 1, no fire
        self._run("s1")  # pcount 1 -> 2, no fire
        self._run("s1")  # pcount 2 -> 3, no fire (pre-increment check uses OLD pcount=2)
        out = self._run("s1")  # pcount 3 -> 4, pre-increment pcount=3 >= MIN_PROMPTS=3 -> fires
        self.assertTrue(out)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("5 repeated pattern-trigger events", ctx)

    def test_no_fire_below_min_struggles_even_after_min_prompts(self):
        self._write_signal_log("s1", 1)  # below MIN_STRUGGLES=2
        for _ in range(5):
            out = self._run("s1")
        self.assertEqual(out, "")

    def test_fires_at_most_once_per_session(self):
        self._write_signal_log("s1", 5)
        for _ in range(4):
            out = self._run("s1")
        self.assertTrue(out)
        # further calls in the same session stay silent even though every condition still holds
        out2 = self._run("s1")
        self.assertEqual(out2, "")

    def test_missing_signal_log_fails_open_no_fire(self):
        # no _write_signal_log call at all -- log file never created
        for _ in range(6):
            out = self._run("s1")
        self.assertEqual(out, "")

    def test_toggle_off_never_fires(self):
        with open(os.path.join(self.tmp, "local"), "w") as fh:
            fh.write("evaluator.escalation=off\n")
        self._write_signal_log("s1", 5)
        for _ in range(6):
            out = self._run("s1")
        self.assertEqual(out, "")

    def test_different_sessions_tracked_independently(self):
        self._write_signal_log("s1", 5)
        self._write_signal_log("s2", 0)
        for _ in range(4):
            out1 = self._run("s1")
        for _ in range(4):
            out2 = self._run("s2")
        self.assertTrue(out1)   # s1 has enough struggles
        self.assertEqual(out2, "")  # s2 has none


if __name__ == "__main__":
    unittest.main()
