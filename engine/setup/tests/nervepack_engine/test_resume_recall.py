"""Tests for nervepack_engine.hooks.resume_recall — the Python port of
np-resume-recall.sh. Ports all 6 scenarios from
engine/setup/tests/resume/test_resume_recall.sh, including the bash test's
own non-vacuity technique for the stale-pointer case (verify a broken
freshness check WOULD produce an offer, before verifying the real one
doesn't)."""
import json
import os
import sys
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _seed_pointer(path, sid, ts, branch, head, dirty, ledger, plan, last):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "session_id": sid, "ts": ts, "cwd": "/tmp/prior-cwd",
                   "git_branch": branch, "git_head": head, "git_dirty": dirty,
                   "transcript_path": "/tmp/prior-transcript.jsonl",
                   "last_user_instruction": last, "sdd_ledger": ledger, "sdd_plan": plan}, fh)


class TestResumeRecall(unittest.TestCase):
    def setUp(self):
        import tempfile, subprocess
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo, exist_ok=True)
        subprocess.run(["git", "-C", self.repo, "init", "-q", "-b", "main"], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.name", "T"], check=True)
        with open(os.path.join(self.repo, "README.md"), "w") as fh:
            fh.write("hello\n")
        subprocess.run(["git", "-C", self.repo, "add", "README.md"], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "-m", "baseline"], check=True)
        self.transcript = os.path.join(self.tmp, "transcript.jsonl")
        with open(self.transcript, "w") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                                  "content": [{"type": "text", "text": "hi"}]}}) + "\n")
            fh.write(json.dumps({"type": "user", "promptSource": "typed",
                                  "message": {"role": "user", "content": "keep going on the current work"}}) + "\n")
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        open(self.toggles_conf, "w").close()
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _case_env(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        pointer = os.path.join(d, "pointer.json")
        env = {
            "NP_RESUME_POINTER": pointer,
            "NP_RESUME_STATE_DIR": os.path.join(d, "state"),
            "NP_RESUME_STAMP": os.path.join(d, "last-write"),
            "NP_RESUME_LOG": os.path.join(d, "resume.log"),
        }
        return pointer, env

    def _payload(self, sid):
        return json.dumps({"session_id": sid, "prompt": "resume this", "cwd": self.repo,
                            "transcript_path": self.transcript})

    def _run(self, sid):
        from nervepack_engine.hooks import resume_recall
        return resume_recall.run(self._payload(sid))

    def test_1_and_2_offer_then_current_pointer_written(self):
        pointer, env = self._case_env("case1")
        with mock.patch.dict(os.environ, env):
            now = int(time.time())
            _seed_pointer(pointer, "prior-session-123", now, "feature/prior-branch", "abc1234",
                          False, "/tmp/prior-repo/.superpowers/sdd/progress.md", "some/plan.md",
                          "finish the widget refactor")
            out = self._run("current-session-456")
            ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("feature/prior-branch", ctx)
            self.assertIn("prior-repo/.superpowers/sdd/progress.md", ctx)
            self.assertIn("finish the widget refactor", ctx)
            with open(pointer, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["session_id"], "current-session-456")

    def test_3_once_guard_suppresses_repeat_offer(self):
        pointer, env = self._case_env("case3")
        with mock.patch.dict(os.environ, env):
            _seed_pointer(pointer, "prior", int(time.time()), "b", "h", False, "", "", "")
            self._run("current-session-456")
            _seed_pointer(pointer, "prior", int(time.time()), "b", "h", False, "", "", "")
            out2 = self._run("current-session-456")
            self.assertEqual(out2, "")

    def test_4_same_session_pointer_silent(self):
        pointer, env = self._case_env("case4")
        with mock.patch.dict(os.environ, env):
            _seed_pointer(pointer, "same-session-789", int(time.time()), "b", "h", False, "", "", "")
            out = self._run("same-session-789")
            self.assertEqual(out, "")

    def test_5_stale_pointer_silent_with_non_vacuity_check(self):
        from nervepack_engine.hooks import resume_recall

        # Environment A: an isolated case dir used ONLY to demonstrate that a
        # broken freshness check would wrongly offer. Its side effects (the
        # pointer overwrite from resume_write.write(), the once-per-session
        # marker file) must never leak into environment B's real check below
        # -- that leakage is exactly the vacuity bug this test was rewritten
        # to close.
        pointer_a, env_a = self._case_env("case5-demo")
        with mock.patch.dict(os.environ, env_a):
            stale_ts = int(time.time()) - 999999
            _seed_pointer(pointer_a, "prior-a", stale_ts, "b", "h", False, "", "", "")
            with mock.patch.object(resume_recall, "_is_fresh", return_value=True):
                broken_out = resume_recall.run(self._payload("demo-sid"))
            self.assertTrue(broken_out, "non-vacuity: broken freshness check unexpectedly silent")

        # Environment B: a completely separate, freshly-created case dir --
        # its own pointer file, state dir, and session id -- seeded with its
        # own stale pointer. Nothing from environment A can leak in here.
        pointer_b, env_b = self._case_env("case5-real")
        with mock.patch.dict(os.environ, env_b):
            stale_ts = int(time.time()) - 999999
            _seed_pointer(pointer_b, "prior-b", stale_ts, "b", "h", False, "", "", "")
            # Wrap (don't stub) the real _is_fresh so we can prove it was
            # actually invoked on this path -- this is what makes the
            # non-vacuity check genuine rather than trusted: silence here
            # must come from the freshness gate itself, not from a
            # same-session or once-guard side effect.
            with mock.patch.object(resume_recall, "_is_fresh", wraps=resume_recall._is_fresh) as spy:
                out = self._run("real-check-sid")
                self.assertGreaterEqual(
                    spy.call_count, 1,
                    "non-vacuity: _is_fresh was never invoked on the real check path")
            self.assertEqual(out, "")

    def test_6_toggle_off_silent_and_no_write(self):
        pointer, env = self._case_env("case6")
        with mock.patch.dict(os.environ, env):
            _seed_pointer(pointer, "prior", int(time.time()), "b", "h", False, "", "", "")
            with open(pointer, "rb") as fh:
                before = fh.read()
            with open(self.toggles_conf, "w") as fh:
                fh.write("resume|shared|runtime|off|\n")
            out = self._run("toggle-off-sid")
            self.assertEqual(out, "")
            with open(pointer, "rb") as fh:
                after = fh.read()
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
