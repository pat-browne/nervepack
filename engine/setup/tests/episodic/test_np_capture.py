"""Direct unit tests for np_capture.capture() -- the already-existing, in-process
Python port of episodic-capture.sh's orchestration logic (consumed today by
backcapture_sweep.py and the MCP server's bash-free fallback). Written as part
of retiring episodic-capture.sh and its bash test suite (including
tests/mcp/parity/test_capture_parity.sh, which can no longer run once the bash
side is deleted) -- these tests replace the verification value the parity test
provided, direct rather than by A/B comparison against bash."""
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is engine/setup/tests/episodic -- two levels up is engine/setup
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_capture  # noqa: E402


class TestNpCapture(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("memory|shared|runtime|on|\n")
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
            "EPISODIC_INBOX": os.path.join(self.tmp, "inbox"),
            "EPISODIC_SEEN_DIR": os.path.join(self.tmp, "seen"),
            "EPISODIC_CAPTURE_LOG": os.path.join(self.tmp, "capture.log"),
            "CLAUDE_BIN": self.claude_bin,
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("NERVEPACK_AGENT", None)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _payload(self, cwd="proj"):
        return {"transcript_path": self.transcript, "cwd": cwd, "session_id": "sid-1"}

    def _inbox_line(self):
        inbox = os.environ["EPISODIC_INBOX"]
        files = os.listdir(inbox)
        self.assertEqual(len(files), 1)
        with open(os.path.join(inbox, files[0]), encoding="utf-8") as fh:
            return fh.read().strip()

    def test_1_happy_path_writes_note_and_redacts_secret(self):
        note = ('{"headline":"did the thing","body":"worked on oauth using '
                'sk-ABCDEFGHIJKLMNOPQRSTUV today","candidate_topics":["auth"],'
                '"keywords":["oauth"]}')
        with mock.patch.object(np_capture.np_model, "complete", return_value=note):
            status = np_capture.capture(self._payload(cwd="/x/proj"), mode="session-end")
        self.assertEqual(status, "captured")
        line = self._inbox_line()
        record = json.loads(line)
        self.assertEqual(record["headline"], "did the thing")
        self.assertEqual(record["mode"], "session-end")
        self.assertEqual(record["project"], "proj")
        self.assertNotIn("sk-ABCDEFG", line)
        self.assertIn("REDACTED", line)

    def test_2_non_json_summarizer_output_bails_logged_no_inbox_write(self):
        with mock.patch.object(np_capture.np_model, "complete", return_value="not json at all"):
            status = np_capture.capture(self._payload(), mode="session-end")
        self.assertEqual(status, "captured")
        inbox = os.environ["EPISODIC_INBOX"]
        self.assertFalse(os.path.isdir(inbox) and os.listdir(inbox))
        log = os.environ["EPISODIC_CAPTURE_LOG"]
        with open(log, encoding="utf-8") as fh:
            self.assertIn("bail", fh.read())

    def test_3_dedup_unchanged_transcript_skips_second_capture(self):
        note = '{"headline":"h","body":"b","candidate_topics":[],"keywords":[]}'
        with mock.patch.object(np_capture.np_model, "complete", return_value=note) as m:
            np_capture.capture(self._payload(), mode="session-end")
            m.reset_mock()
            np_capture.capture(self._payload(), mode="session-end")
            m.assert_not_called()

    def test_4_missing_transcript_fails_open_no_model_call(self):
        payload = {"transcript_path": os.path.join(self.tmp, "nope.jsonl"), "cwd": "x"}
        with mock.patch.object(np_capture.np_model, "complete") as m:
            status = np_capture.capture(payload, mode="session-end")
            m.assert_not_called()
        self.assertEqual(status, "captured")

    def test_5_toggle_off_no_model_call_no_write(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("memory|shared|runtime|off|\n")
        with mock.patch.object(np_capture.np_model, "complete") as m:
            status = np_capture.capture(self._payload(), mode="session-end")
            m.assert_not_called()
        self.assertEqual(status, "captured")
        inbox = os.environ["EPISODIC_INBOX"]
        self.assertFalse(os.path.isdir(inbox))

    def test_6_reentry_guard_no_model_call(self):
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            with mock.patch.object(np_capture.np_model, "complete") as m:
                status = np_capture.capture(self._payload(), mode="session-end")
                m.assert_not_called()
        self.assertEqual(status, "captured")

    def test_7_checkpoint_mode_recorded_in_envelope(self):
        note = '{"headline":"h","body":"b","candidate_topics":[],"keywords":[]}'
        with mock.patch.object(np_capture.np_model, "complete", return_value=note):
            np_capture.capture(self._payload(), mode="checkpoint")
        record = json.loads(self._inbox_line())
        self.assertEqual(record["mode"], "checkpoint")

    def test_8_struggles_and_strategies_passthrough_with_redaction(self):
        # Ported from the retiring tests/playbook/test_capture_strategies.sh and
        # test_capture_struggles.sh -- struggles[]/strategies[] arrays survive
        # capture + scrub into the inbox record, secrets redacted, symmetric to
        # the top-level body/headline redaction in test_1.
        note = json.dumps({
            "headline": "h", "body": "b", "candidate_topics": ["t"], "keywords": ["k"],
            "struggles": [{
                "symptom": "blanket sed corrupted names", "cause": "substring collision",
                "fix": "guarded pass; token ghp_ABCDEFGHIJKLMNOPQRSTU",
                "tool_match": "sed -i", "topic_triggers": ["rename", "sed"],
                "destructive": False,
            }],
            "strategies": [{
                "title": "Mirror the proven pipeline", "description": "when adding a memory layer",
                "content": "reuse capture->inbox->maintain->recall; token ghp_ABCDEFGHIJKLMNOPQRSTU",
                "topic_triggers": ["memory", "layer"],
            }],
        })
        with mock.patch.object(np_capture.np_model, "complete", return_value=note):
            np_capture.capture(self._payload(), mode="session-end")
        line = self._inbox_line()
        record = json.loads(line)
        self.assertEqual(record["struggles"][0]["symptom"], "blanket sed corrupted names")
        self.assertEqual(record["struggles"][0]["tool_match"], "sed -i")
        self.assertEqual(record["strategies"][0]["title"], "Mirror the proven pipeline")
        self.assertIn("memory", record["strategies"][0]["topic_triggers"])
        self.assertNotIn("ghp_ABCDEFG", line)
        self.assertIn("REDACTED", line)

    def test_9_bail_never_raises_when_log_dir_unwritable(self):
        # Ported from the retiring tests/toggles/test_hook_bail_unwritable_log.sh --
        # invariant 1 (fail-open): a bail() call must never raise even when its own
        # breadcrumb log can't be written (parent path blocked by a regular file).
        # Force a real bail branch (dedup skip) rather than a synthetic one.
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w") as fh:
            fh.write("i am a file, not a dir\n")
        unwritable_log = os.path.join(blocker, "capture.log")  # parent is a FILE
        fp = str(os.path.getsize(self.transcript))
        seen_dir = os.environ["EPISODIC_SEEN_DIR"]
        os.makedirs(seen_dir, exist_ok=True)
        with open(os.path.join(seen_dir, "sid-1"), "w") as fh:
            fh.write(fp)
        with mock.patch.dict(os.environ, {"EPISODIC_CAPTURE_LOG": unwritable_log}):
            with mock.patch.object(np_capture.np_model, "complete") as m:
                status = np_capture.capture(self._payload(), mode="session-end")
                m.assert_not_called()
        self.assertEqual(status, "captured")
        self.assertFalse(os.path.exists(unwritable_log))
        self.assertTrue(os.path.isfile(blocker))


if __name__ == "__main__":
    unittest.main()
