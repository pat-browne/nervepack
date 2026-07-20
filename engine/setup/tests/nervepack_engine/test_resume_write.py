"""Tests for nervepack_engine.hooks.resume_write — the Python port of
np-resume-write.sh. Ports all 10 scenarios from
engine/setup/tests/resume/test_resume_write.sh: base field correctness,
git_dirty flipping, throttle vs always-write, toggle-off, non-git cwd,
trailing value-less flag (N/A in Python — argparse-style parsing has no
shift-loop hang class, noted as a structural non-issue rather than ported
1:1), throttle-with-stale-stamp, plan-less ledger, ledger-less git repo."""
import json
import os
import sys
import unittest
from unittest import mock

# _HERE is engine/setup/tests/nervepack_engine — two levels up is engine/setup
# (needed so resume_write.py's own `import np_toggle` resolves when this test
# imports it directly, bypassing cli.py's own sys.path fixup), three levels up
# is engine/ (needed for `import nervepack_engine`).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _git(cwd, *args):
    import subprocess
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True)


def _init_repo(path, with_ledger=True, with_plan=True):
    os.makedirs(path, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    with open(os.path.join(path, "README.md"), "w") as fh:
        fh.write("hello\n")
    if with_ledger:
        os.makedirs(os.path.join(path, ".superpowers", "sdd"), exist_ok=True)
        with open(os.path.join(path, ".superpowers", "sdd", "progress.md"), "w") as fh:
            if with_plan:
                fh.write("# Progress\n\nPlan: some/path.md\n\nStatus: in progress\n")
            else:
                fh.write("# Progress\n\nStatus: going\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "baseline")


class TestResumeWrite(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        _init_repo(self.repo)
        self.transcript = os.path.join(self.tmp, "transcript.jsonl")
        with open(self.transcript, "w") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                                  "content": [{"type": "text", "text": "hi"}]}}) + "\n")
            fh.write(json.dumps({"type": "user", "promptSource": "typed",
                                  "message": {"role": "user", "content": "resume the widget refactor"}}) + "\n")
        self.pointer = os.path.join(self.tmp, "pointer.json")
        self.stamp = os.path.join(self.tmp, "last-write")
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        open(self.toggles_conf, "w").close()
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
            "NP_RESUME_POINTER": self.pointer,
            "NP_RESUME_STAMP": self.stamp,
            "NP_RESUME_LOG": os.path.join(self.tmp, "resume.log"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _pointer(self):
        with open(self.pointer, encoding="utf-8") as fh:
            return json.load(fh)

    def test_1_base_fields(self):
        from nervepack_engine.hooks import resume_write
        resume_write.write(session="test-session-123", transcript=self.transcript, cwd=self.repo)
        self.assertTrue(os.path.isfile(self.pointer))
        p = self._pointer()
        self.assertEqual(p["session_id"], "test-session-123")
        self.assertEqual(p["cwd"], self.repo)
        self.assertEqual(p["git_dirty"], False)
        self.assertEqual(p["transcript_path"], self.transcript)
        self.assertEqual(p["last_user_instruction"], "resume the widget refactor")
        self.assertTrue(p["sdd_ledger"].endswith(".superpowers/sdd/progress.md"))
        self.assertEqual(p["sdd_plan"], "some/path.md")
        self.assertEqual(p["schema_version"], 1)
        self.assertIsInstance(p["ts"], int)
        self.assertTrue(p["git_head"])
        self.assertTrue(p["git_branch"])

    def test_2_git_dirty_flips_true(self):
        from nervepack_engine.hooks import resume_write
        with open(os.path.join(self.repo, "scratch.txt"), "w") as fh:
            fh.write("uncommitted\n")
        resume_write.write(session="s", transcript=self.transcript, cwd=self.repo)
        self.assertTrue(self._pointer()["git_dirty"])

    def test_3_throttle_blocks_within_interval(self):
        from nervepack_engine.hooks import resume_write
        resume_write.write(session="first", transcript=self.transcript, cwd=self.repo)
        with open(self.stamp, "w") as fh:
            fh.write(str(int(__import__("time").time())))
        resume_write.write(session="should-not-appear", transcript=self.transcript, cwd=self.repo, throttle=True)
        self.assertEqual(self._pointer()["session_id"], "first")

    def test_4_non_throttled_always_writes(self):
        from nervepack_engine.hooks import resume_write
        resume_write.write(session="first", transcript=self.transcript, cwd=self.repo)
        with open(self.stamp, "w") as fh:
            fh.write(str(int(__import__("time").time())))
        resume_write.write(session="second", transcript=self.transcript, cwd=self.repo)
        self.assertEqual(self._pointer()["session_id"], "second")

    def test_5_toggle_off_no_write(self):
        from nervepack_engine.hooks import resume_write
        with open(self.toggles_conf, "w") as fh:
            fh.write("resume|shared|runtime|off|\n")
        resume_write.write(session="off-test", transcript=self.transcript, cwd=self.repo)
        self.assertFalse(os.path.isfile(self.pointer))

    def test_6_non_git_cwd(self):
        from nervepack_engine.hooks import resume_write
        nongit = os.path.join(self.tmp, "nongit")
        os.makedirs(nongit, exist_ok=True)
        resume_write.write(session="nongit-test", transcript=self.transcript, cwd=nongit)
        p = self._pointer()
        self.assertEqual(p["git_branch"], "")
        self.assertEqual(p["git_head"], "")
        self.assertFalse(p["git_dirty"])
        self.assertEqual(p["sdd_ledger"], "")
        self.assertEqual(p["sdd_plan"], "")

    def test_7_throttle_with_stale_stamp_writes_through(self):
        from nervepack_engine.hooks import resume_write
        with open(self.stamp, "w") as fh:
            fh.write(str(int(__import__("time").time()) - 99999))
        resume_write.write(session="stale-throttle", transcript=self.transcript, cwd=self.repo, throttle=True)
        self.assertEqual(self._pointer()["session_id"], "stale-throttle")

    def test_8_planless_ledger(self):
        from nervepack_engine.hooks import resume_write
        planless = os.path.join(self.tmp, "planless")
        _init_repo(planless, with_ledger=True, with_plan=False)
        resume_write.write(session="planless", transcript=self.transcript, cwd=planless)
        p = self._pointer()
        self.assertTrue(p["sdd_ledger"].endswith(".superpowers/sdd/progress.md"))
        self.assertEqual(p["sdd_plan"], "")

    def test_9_git_repo_without_ledger(self):
        from nervepack_engine.hooks import resume_write
        noledger = os.path.join(self.tmp, "noledger")
        _init_repo(noledger, with_ledger=False)
        resume_write.write(session="noledger", transcript=self.transcript, cwd=noledger)
        p = self._pointer()
        self.assertEqual(p["sdd_ledger"], "")
        self.assertEqual(p["sdd_plan"], "")
        self.assertTrue(p["git_head"])

    def test_10_missing_cwd_is_a_silent_noop(self):
        # Python's function-call interface has no positional-flag-parsing hang
        # class (that was specific to bash's manual `shift 2` loop) -- the
        # equivalent case here is simply "no cwd provided", which must be a
        # silent no-op (mirrors bash's `bail "missing required --cwd"`).
        from nervepack_engine.hooks import resume_write
        resume_write.write(session="s", transcript=self.transcript, cwd=None)
        self.assertFalse(os.path.isfile(self.pointer))


if __name__ == "__main__":
    unittest.main()
