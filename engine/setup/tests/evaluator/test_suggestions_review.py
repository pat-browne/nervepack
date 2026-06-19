#!/usr/bin/env python3
"""Contract test for setup/np-suggestions-review.py (stdlib unittest — no pytest,
per the harness language policy). Black-box: runs the script as a subprocess with
explicit --metrics/--resolved paths and asserts on stdout / the resolved ledger."""
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW = os.path.join(HERE, "..", "..", "np-suggestions-review.py")

# 3 sessions: "alpha" appears twice (dedupe + count), confidences vary.
FIXTURE = "".join([
    '{"session_id":"s1","ts":"2026-06-01T10:00:00Z","suggestions":['
    '{"text":"Do alpha","confidence":0.9,"target":"hooks","auto_safe":true},'
    '{"text":"Do beta","confidence":0.5,"target":"skills","auto_safe":false}]}\n',
    '{"session_id":"s2","ts":"2026-06-02T10:00:00Z","suggestions":['
    '{"text":"Do   ALPHA","confidence":0.7,"target":"hooks"},'
    '{"text":"Do gamma","confidence":0.95,"target":"other","auto_safe":true}]}\n',
    '{"session_id":"s3","ts":"2026-06-03T10:00:00Z","suggestions":[]}\n',
])


def run(args, metrics, resolved):
    return subprocess.run(
        ["python3", REVIEW, "--metrics", metrics, "--resolved", resolved] + args,
        check=True, capture_output=True, text=True).stdout


class TestReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.metrics = os.path.join(self.tmp.name, "metrics.jsonl")
        self.resolved = os.path.join(self.tmp.name, "resolved.txt")
        with open(self.metrics, "w") as fh:
            fh.write(FIXTURE)

    def tearDown(self):
        self.tmp.cleanup()

    def _open(self):
        return json.loads(run(["list", "--top", "0", "--json"], self.metrics, self.resolved))

    def test_rank_dedupe_and_count(self):
        rows = self._open()
        # gamma (.95) > alpha (.90, deduped from .9/.7, count 2) > beta (.50)
        self.assertEqual([r["text"] for r in rows], ["Do gamma", "Do alpha", "Do beta"])
        alpha = next(r for r in rows if r["text"] == "Do alpha")
        self.assertEqual(alpha["count"], 2)          # both sessions, one entry
        self.assertEqual(alpha["confidence"], 0.9)   # max confidence kept
        self.assertTrue(alpha["auto_safe"])          # OR'd across occurrences

    def test_top_n_limits(self):
        rows = json.loads(run(["list", "--top", "2", "--json"], self.metrics, self.resolved))
        self.assertEqual([r["text"] for r in rows], ["Do gamma", "Do alpha"])

    def test_clear_resolves_all_and_is_idempotent(self):
        out = run(["clear", "--no-build"], self.metrics, self.resolved)
        self.assertIn("cleared 3", out)
        self.assertEqual(self._open(), [])           # panel now empty
        with open(self.resolved) as fh:
            lines = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
        self.assertEqual(len(lines), 3)
        # Re-clearing adds nothing (everything already resolved).
        self.assertIn("cleared 0", run(["clear", "--no-build"], self.metrics, self.resolved))
        with open(self.resolved) as fh:
            again = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
        self.assertEqual(len(again), 3)

    def test_clear_top_n_leaves_the_rest_open(self):
        run(["clear", "--top", "1", "--no-build"], self.metrics, self.resolved)
        self.assertEqual([r["text"] for r in self._open()], ["Do alpha", "Do beta"])

    def test_already_resolved_is_excluded(self):
        with open(self.resolved, "w") as fh:
            fh.write("do alpha\n")                    # lowercase -> normalized match
        self.assertEqual([r["text"] for r in self._open()], ["Do gamma", "Do beta"])

    def test_empty_metrics_lists_nothing(self):
        open(self.metrics, "w").close()
        self.assertEqual(self._open(), [])
        self.assertIn("No open suggestions", run(["list"], self.metrics, self.resolved))


if __name__ == "__main__":
    unittest.main()
