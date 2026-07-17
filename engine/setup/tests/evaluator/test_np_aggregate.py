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
