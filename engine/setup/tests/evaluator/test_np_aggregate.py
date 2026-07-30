"""Direct unit tests for np_aggregate.py -- the Python port of
73-aggregate-metrics.sh. Ports test_aggregate.sh/test_aggregate_commit_scope.sh/
test_retention.sh's scenarios. Deterministic, no LLM -- no model seam to mock."""
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "nervepack_engine")))  # phase 20b-2: relocated library modules

import np_aggregate  # noqa: E402


def _init_repo(path):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "-C", path, "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "T"], check=True)
    with open(os.path.join(path, "README.md"), "w") as fh:
        fh.write("hello\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", "baseline"], check=True)


class TestNpAggregate(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        # A sandboxed, empty HOME -- critical for test_4 below: np_content.py's
        # implicit-fallback resolution reads ~/.config/nervepack/content-dir when
        # NP_CONTENT_DIR is unset, so HOME must be sandboxed here (not just NP_
        # env vars) or that test would silently read the REAL developer machine's
        # actual content-dir config instead of exercising the fallback path.
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home, exist_ok=True)
        self.repo = os.path.join(self.tmp, "repo")
        _init_repo(self.repo)
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard=off\n")
        self.inbox = os.path.join(self.tmp, "inbox")
        self.metrics = os.path.join(self.repo, "dashboard", "data", "metrics.jsonl")
        self._env = mock.patch.dict(os.environ, {
            "HOME": self.home,
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
            "NP_CONTENT_DIR": self.repo,
            "EVAL_INBOX": self.inbox,
            "METRICS_FILE": self.metrics,
            "NP_RESOLVED_SUGGESTIONS": os.path.join(self.repo, "dashboard", "data", "resolved-suggestions.txt"),
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write_inbox_record(self, ts=None, **extra):
        os.makedirs(self.inbox, exist_ok=True)
        rec = {"ts": ts or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "session_id": "s1"}
        rec.update(extra)
        with open(os.path.join(self.inbox, "batch.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")

    def test_1_drains_inbox_into_metrics_and_commits(self):
        self._write_inbox_record()
        status = np_aggregate.aggregate()
        self.assertEqual(status, "aggregated")
        with open(self.metrics, encoding="utf-8") as fh:
            self.assertEqual(len(fh.readlines()), 1)
        log = subprocess.run(["git", "-C", self.repo, "log", "-1", "--format=%s"],
                              capture_output=True, text=True).stdout
        self.assertIn("evaluator(metrics): daily batch", log)
        self.assertFalse(os.path.isdir(self.inbox) and os.listdir(self.inbox))

    def _dashboard_on(self):
        """The other tests run with dashboard=off, so metrics.js is never built --
        which is exactly why #202 bug 3 went unnoticed. These need it ON."""
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard=on\n")
            fh.write("memory|shared|runtime|on|backcapture_days=7\n")

    def test_8_volatile_dashboard_field_alone_does_not_trigger_a_commit(self):
        """#202 bug 3: metrics.js is regenerated every run and embeds
        resolved_last_24h -- a rolling count that changes on its own as
        back-capture seen-markers age past 24h. The commit guard diffed
        metrics.js too, so a run with ZERO new records still saw a diff and
        committed, producing near-duplicate 'daily batch — 0 record(s)' commits
        every 30-90s instead of the documented daily cadence."""
        self._dashboard_on()
        seen_dir = os.path.join(self.tmp, "bc-seen")
        os.makedirs(seen_dir, exist_ok=True)
        for name in ("aaaa", "bbbb"):
            open(os.path.join(seen_dir, name), "a").close()

        with mock.patch.dict(os.environ, {
                "BACKCAPTURE_SEEN_DIR": seen_dir,
                "BACKCAPTURE_QUEUE_DIR": os.path.join(self.tmp, "bc-queue")}):
            self._write_inbox_record()
            self.assertEqual(np_aggregate.aggregate(), "aggregated")
            before = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                    capture_output=True, text=True).stdout

            # Age one marker past the 24h window: resolved_last_24h drops 2 -> 1,
            # so metrics.js genuinely changes while metrics.jsonl does not.
            old = time.time() - 86400 * 2
            os.utime(os.path.join(seen_dir, "aaaa"), (old, old))

            status = np_aggregate.aggregate()          # empty inbox this time
            after = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout

        self.assertEqual(before, after,
                         "a derived-artifact-only change must not produce a commit")
        self.assertIn("no", status)

    def test_9_no_op_run_leaves_nothing_staged(self):
        """The guard must not stage metrics.js on the way to deciding not to
        commit -- a shared index means the next writer would sweep it up
        (AGENTS.md 'concurrent session')."""
        self._dashboard_on()
        self._write_inbox_record()
        np_aggregate.aggregate()
        np_aggregate.aggregate()                       # second run: nothing new
        staged = subprocess.run(["git", "-C", self.repo, "diff", "--cached", "--name-only"],
                                capture_output=True, text=True).stdout.strip()
        self.assertEqual(staged, "", "no-op run left files staged in a shared index")

    def test_10_a_real_metrics_change_still_commits(self):
        """The guard must not over-correct: genuine new records still land."""
        self._dashboard_on()
        self._write_inbox_record()
        self.assertEqual(np_aggregate.aggregate(), "aggregated")
        self._write_inbox_record()
        before = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout
        self.assertEqual(np_aggregate.aggregate(), "aggregated")
        after = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout
        self.assertNotEqual(before, after, "new records must still produce a commit")
        files = subprocess.run(["git", "-C", self.repo, "log", "-1", "--name-only", "--format="],
                               capture_output=True, text=True).stdout
        self.assertIn("metrics.js", files, "the derived artifact must still ride along")

    def test_2_empty_inbox_no_commit(self):
        before = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout
        status = np_aggregate.aggregate()
        after = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout
        self.assertEqual(before, after)
        self.assertIn("no", status)

    def test_3_toggle_off_no_op(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|off|\n")
        self._write_inbox_record()
        status = np_aggregate.aggregate()
        self.assertIn("skipped", status)
        self.assertFalse(os.path.isfile(self.metrics))

    def test_4_implicit_content_dir_skips_commit(self):
        # NP_CONTENT_DIR unset + no ~/.config/nervepack/content-dir (HOME is a
        # fresh, empty sandbox per setUp) -> np_content.content_is_explicit()
        # is False, falling back to the implicit engine-root default.
        os.environ.pop("NP_CONTENT_DIR", None)
        self._write_inbox_record()
        status = np_aggregate.aggregate()
        self.assertIn("skipped", status)

    def test_5_retention_prunes_old_records(self):
        old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 200 * 86400))
        self._write_inbox_record(ts=old_ts)
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard=off,retain_days=90\n")
        np_aggregate.aggregate()
        with open(self.metrics, encoding="utf-8") as fh:
            lines = fh.readlines()
        self.assertEqual(len(lines), 0)

    def test_6_retention_zero_means_unlimited(self):
        old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 200 * 86400))
        self._write_inbox_record(ts=old_ts)
        with open(self.toggles_conf, "w") as fh:
            fh.write("evaluator|shared|runtime|on|dashboard=off,retain_days=0\n")
        np_aggregate.aggregate()
        with open(self.metrics, encoding="utf-8") as fh:
            lines = fh.readlines()
        self.assertEqual(len(lines), 1)

    def test_7_second_run_paths_only_dont_sweep_unrelated_staged_file(self):
        # Issue #11 regression: a concurrent session's staged, unrelated file must
        # survive an aggregate commit untouched (path-limited add+commit).
        self._write_inbox_record()
        other = os.path.join(self.repo, "other.txt")
        with open(other, "w") as fh:
            fh.write("someone else's WIP\n")
        subprocess.run(["git", "-C", self.repo, "add", "other.txt"], check=True)
        np_aggregate.aggregate()
        status = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"],
                                 capture_output=True, text=True).stdout
        self.assertIn("other.txt", status)  # still staged, not swept into our commit
        log = subprocess.run(["git", "-C", self.repo, "log", "-1", "--name-only", "--format="],
                              capture_output=True, text=True).stdout
        self.assertNotIn("other.txt", log)


if __name__ == "__main__":
    unittest.main()
