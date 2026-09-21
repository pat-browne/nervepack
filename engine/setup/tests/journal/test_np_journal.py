"""Direct unit tests for np_journal (session journal feature)."""
import json
import os
import sys
import tempfile
import time
import shutil
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine")))

import np_journal  # noqa: E402


class JournalBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.jdir = os.path.join(self.tmp, "journal")
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("journal|shared|runtime|on|model=haiku,ttl_days=30,recall_sources=compact+resume\n")
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        self._env = mock.patch.dict(os.environ, {
            "NP_SESSION_JOURNAL_DIR": self.jdir,
            "NP_JOURNAL_LOG": os.path.join(self.tmp, "j.log"),
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("NERVEPACK_AGENT", None)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write_transcript(self, first_prompt="fix the bug"):
        rec = {"type": "user", "promptSource": "typed",
               "message": {"content": first_prompt}}
        with open(self.transcript, "w") as fh:
            fh.write(json.dumps(rec) + "\n")

    def _payload(self, **kw):
        p = {"session_id": "sid-1", "transcript_path": self.transcript, "cwd": "proj"}
        p.update(kw)
        return p

    def _read(self, sid="sid-1"):
        with open(np_journal.journal_path(sid), encoding="utf-8") as fh:
            return fh.read()


class TestSeed(JournalBase):
    def test_seed_sets_goal_from_first_prompt(self):
        self._write_transcript("implement session journal")
        np_journal.seed(self._payload())
        body = self._read()
        self.assertIn("**Goal:** implement session journal", body)
        self.assertIn("**Hypotheses:** TBD", body)
        self.assertIn("SessionStart", body)

    def test_seed_no_transcript_is_noop(self):
        np_journal.seed(self._payload(transcript_path=""))
        self.assertFalse(os.path.exists(np_journal.journal_path("sid-1")))

    def test_seed_empty_transcript_no_model_no_file(self):
        with open(self.transcript, "w") as fh:
            fh.write("")
        np_journal.seed(self._payload())
        self.assertFalse(os.path.exists(np_journal.journal_path("sid-1")))

    def test_seed_includes_repo_metadata_in_git_repo(self):
        self._write_transcript("do work")
        repo = os.path.join(self.tmp, "r")
        os.makedirs(repo)
        import subprocess
        subprocess.run(["git", "init", "-q", repo], check=True)
        np_journal.seed(self._payload(cwd=repo))
        body = self._read()
        self.assertIn("**Repo:** r @", body)
        self.assertIn("checkout", body)

    def test_seed_no_repo_metadata_outside_git(self):
        self._write_transcript("do work")
        np_journal.seed(self._payload(cwd=self.tmp))
        self.assertNotIn("**Repo:**", self._read())


class TestCheckpoint(JournalBase):
    def _complete(self, *_a, **_k):
        return json.dumps({"goal": "G", "hypotheses": "H", "struggles": "S",
                           "progress": "P", "skills": "np-flow-develop, TDD"})

    def test_checkpoint_appends_all_fields(self):
        self._write_transcript()
        np_journal.checkpoint(self._payload(), complete_fn=self._complete)
        body = self._read()
        self.assertIn("**Goal:** G", body)
        self.assertIn("**Progress:** P", body)
        self.assertIn("**Skills:** np-flow-develop, TDD", body)
        self.assertIn("PreCompact", body)

    def test_checkpoint_appends_not_overwrites(self):
        self._write_transcript()
        np_journal.seed(self._payload())
        np_journal.checkpoint(self._payload(), complete_fn=self._complete)
        body = self._read()
        self.assertIn("SessionStart", body)
        self.assertIn("PreCompact", body)

    def test_checkpoint_model_error_is_failopen(self):
        self._write_transcript()

        def boom(*_a, **_k):
            raise RuntimeError("model down")

        np_journal.checkpoint(self._payload(), complete_fn=boom)
        self.assertFalse(os.path.exists(np_journal.journal_path("sid-1")))

    def test_checkpoint_agent_guard(self):
        self._write_transcript()
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            np_journal.checkpoint(self._payload(), complete_fn=self._complete)
        self.assertFalse(os.path.exists(np_journal.journal_path("sid-1")))


class TestRecall(JournalBase):
    def setUp(self):
        super().setUp()
        self._write_transcript()
        np_journal.append_block("sid-1", "SessionStart", {"goal": "G"})

    def test_compact_injects(self):
        out = np_journal.recall_sessionstart(self._payload(source="compact"))
        self.assertIn("**Goal:** G", out)

    def test_resume_injects(self):
        out = np_journal.recall_sessionstart(self._payload(source="resume"))
        self.assertIn("restored after resume", out)

    def test_startup_silent(self):
        self.assertEqual(np_journal.recall_sessionstart(self._payload(source="startup")), "")

    def test_clear_silent(self):
        self.assertEqual(np_journal.recall_sessionstart(self._payload(source="clear")), "")

    def test_fallback_silent_after_done(self):
        np_journal.recall_sessionstart(self._payload(source="compact"))
        self.assertEqual(np_journal.recall_fallback(self._payload()), "")

    def test_fallback_silent_on_plain_startup(self):
        np_journal.recall_sessionstart(self._payload(source="startup"))
        self.assertEqual(np_journal.recall_fallback(self._payload()), "")

    def test_fallback_injects_when_pending_without_done(self):
        # simulate interrupted SessionStart: pending exists, done missing
        np_journal._touch(np_journal._receipt("sid-1", "pending"))
        out = np_journal.recall_fallback(self._payload())
        self.assertIn("**Goal:** G", out)
        # second call is silent
        self.assertEqual(np_journal.recall_fallback(self._payload()), "")


class TestCleanup(JournalBase):
    def test_cleanup_removes_file_and_receipts(self):
        np_journal.append_block("sid-1", "SessionStart", {"goal": "G"})
        np_journal._touch(np_journal._receipt("sid-1", "pending"))
        np_journal.cleanup("sid-1")
        self.assertFalse(os.path.exists(np_journal.journal_path("sid-1")))
        self.assertFalse(os.path.exists(np_journal._receipt("sid-1", "pending")))

    def test_ttl_removes_old_keeps_new(self):
        np_journal.append_block("old", "SessionStart", {"goal": "G"})
        np_journal.append_block("new", "SessionStart", {"goal": "G"})
        old = np_journal.journal_path("old")
        past = time.time() - 40 * 86400
        os.utime(old, (past, past))
        removed = np_journal.ttl_sweep()
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(np_journal.journal_path("new")))


class TestToggleOff(JournalBase):
    def setUp(self):
        super().setUp()
        with open(self.toggles_conf, "w") as fh:
            fh.write("journal|shared|runtime|off|\n")

    def test_seed_noop_when_off(self):
        self._write_transcript()
        np_journal.seed(self._payload())
        self.assertFalse(os.path.exists(np_journal.journal_path("sid-1")))

    def test_recall_silent_when_off(self):
        self.assertEqual(np_journal.recall_sessionstart(self._payload(source="compact")), "")


if __name__ == "__main__":
    unittest.main()
