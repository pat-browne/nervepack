"""Direct unit tests for np_capture.capture() -- the already-existing, in-process
Python port of episodic-capture.sh's orchestration logic. episodic-capture.sh has
been retired (its logic lived here already); this module is now the sole
implementation, called in-process both by the MCP server's `_tool_capture` and
by the `cli.py`-dispatched `nervepack_engine.hooks.episodic_capture` SessionEnd/
PreCompact hook wrapper. Written as part of retiring episodic-capture.sh and its
bash test suite (including tests/mcp/parity/test_capture_parity.sh, which can no
longer run once the bash side is deleted) -- these tests replace the
verification value the parity test provided, direct rather than by A/B
comparison against bash."""
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
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "nervepack_engine")))  # phase 20b-2: relocated library modules

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

    def test_2b_non_object_json_bails_logged_no_inbox_write(self):
        for raw in ('["a", "b"]', '"just a string"', "42"):
            with self.subTest(raw=raw):
                with mock.patch.object(np_capture.np_model, "complete", return_value=raw):
                    status = np_capture.capture(self._payload(), mode="session-end")
                self.assertEqual(status, "captured")
                inbox = os.environ["EPISODIC_INBOX"]
                self.assertFalse(os.path.isdir(inbox) and os.listdir(inbox))
        with open(os.environ["EPISODIC_CAPTURE_LOG"], encoding="utf-8") as fh:
            log = fh.read()
        self.assertEqual(log.count("capture bail"), 3)

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

    def test_8b_stack_facts_passthrough_with_redaction(self):
        # stack_facts[] rides the same capture + scrub path as struggles[] and
        # strategies[], so episodic-maintain can stage them for the wiki.
        note = json.dumps({
            "headline": "h", "body": "b", "candidate_topics": ["t"], "keywords": ["k"],
            "stack_facts": [{
                "stack": "fastapi", "claim": "Depends() results are cached per request",
                "evidence": "calls=1 after two uses; token ghp_ABCDEFGHIJKLMNOPQRSTU",
                "version": "0.115", "source": "",
            }],
        })
        with mock.patch.object(np_capture.np_model, "complete", return_value=note):
            np_capture.capture(self._payload(), mode="session-end")
        line = self._inbox_line()
        record = json.loads(line)
        self.assertEqual(record["stack_facts"][0]["stack"], "fastapi")
        self.assertEqual(record["stack_facts"][0]["version"], "0.115")
        self.assertNotIn("ghp_ABCDEFG", line)
        self.assertIn("REDACTED", line)

    def test_8c_stack_facts_are_sanitized(self):
        # `stack` becomes memory/stack-facts/<stack>.md, so a model-supplied
        # traversal string must never reach the inbox. evidence and source are
        # constrained too.
        good = {"stack": "fastapi", "claim": "c", "version": "1",
                "evidence": "curl https://user:pw@host/x " + "e" * 400,
                "source": "https://docs.example.com/a"}
        note = json.dumps({
            "headline": "h", "body": "b", "candidate_topics": ["t"], "keywords": ["k"],
            "stack_facts": [
                good,
                {"stack": "../../skills/np-core-recall/SKILL", "claim": "c", "evidence": "e"},
                {"stack": "..", "claim": "c", "evidence": "e"},
                {"stack": "Py Thon", "claim": "c", "evidence": "e"},
                {"stack": "", "claim": "c", "evidence": "e"},
                {"stack": 7, "claim": "c", "evidence": "e"},
                "not-a-dict",
                {"stack": "rust", "claim": "c", "evidence": "e",
                 "source": "https://u:p@evil.example/x"},
                {"stack": "go", "claim": "c", "evidence": "e", "source": "file:///etc/passwd"},
                {"stack": "dart", "evidence": "e"},
                {"stack": "dart", "claim": "  ", "evidence": "e"},
                {"stack": "dart", "claim": "c"},
                {"stack": "dart", "claim": "c", "evidence": 5},
            ],
        })
        with mock.patch.object(np_capture.np_model, "complete", return_value=note):
            np_capture.capture(self._payload(), mode="session-end")
        facts = json.loads(self._inbox_line())["stack_facts"]
        self.assertEqual([f["stack"] for f in facts], ["fastapi", "rust", "go"])
        self.assertNotIn("user:pw", facts[0]["evidence"])
        # Capped at 300 before np_scrub runs. Each redaction marker is a few characters longer
        # than the text it replaces, so the bound is 300 plus headroom for several markers.
        self.assertLessEqual(len(facts[0]["evidence"]), 320)
        self.assertEqual(facts[0]["source"], "https://docs.example.com/a")
        self.assertEqual(facts[1]["source"], "")
        self.assertEqual(facts[2]["source"], "")

    def test_8d_dropped_stack_facts_are_counted_in_the_log(self):
        note = json.dumps({
            "headline": "h", "body": "b", "candidate_topics": ["t"], "keywords": ["k"],
            "stack_facts": [{"stack": "../x", "claim": "c", "evidence": "e"},
                            {"stack": "go", "claim": "c", "evidence": "e"}, "junk"],
        })
        with mock.patch.object(np_capture.np_model, "complete", return_value=note):
            np_capture.capture(self._payload(), mode="session-end")
        with open(os.environ["EPISODIC_CAPTURE_LOG"], encoding="utf-8") as fh:
            log = fh.read()
        self.assertIn("dropped 2 invalid stack_facts item(s): 1 bad stack slug, 1 not an object", log)
        self.assertNotIn("../x", log)

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


    # --- write guard: dedup, length and junk checks before an item reaches the inbox ---
    def _struggle(self, symptom, fix="add a stdin=DEVNULL guard to every subprocess call"):
        return {"symptom": symptom, "cause": "c", "fix": fix, "tool_match": "",
                "topic_triggers": ["x"], "destructive": False}

    def _records(self):
        inbox = os.environ["EPISODIC_INBOX"]
        out = []
        for f in sorted(os.listdir(inbox)):
            with open(os.path.join(inbox, f), encoding="utf-8") as fh:
                out += [json.loads(l) for l in fh if l.strip()]
        return out

    def test_guard_drops_junk_short_and_overlong_items(self):
        rec = {"session_id": "s", "struggles": [
            self._struggle("n/a", fix="none"),
            self._struggle("ok"  , fix="ok"),
            self._struggle("x" * 3000),
            self._struggle("CI job hung for six hours with no timeout set"),
        ], "strategies": [{"title": "", "content": "todo"}]}
        self.assertTrue(np_capture.append_note(rec))
        r = self._records()[0]
        self.assertEqual([s["symptom"] for s in r["struggles"]],
                         ["CI job hung for six hours with no timeout set"])
        self.assertEqual(r["strategies"], [])
        self.assertEqual(sorted(d["reason"] for d in r["guard"]["dropped"]),
                         ["junk", "junk", "too-long", "too-short"])

    def test_guard_dedups_within_note_and_against_inbox(self):
        s = self._struggle("CI job hung for six hours with no timeout set")
        np_capture.append_note({"session_id": "a", "struggles": [s, dict(s)]})
        np_capture.append_note({"session_id": "b", "struggles": [dict(s, symptom="CI  job hung for SIX hours with no timeout set.")]})
        recs = self._records()
        self.assertEqual(len(recs[0]["struggles"]), 1)
        self.assertEqual(recs[1]["struggles"], [])
        self.assertEqual(recs[1]["guard"]["dropped"][0]["reason"], "duplicate")

    def test_guard_off_passes_items_through(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("memory|shared|runtime|on|write_guard=off\n")
        np_capture.append_note({"session_id": "s", "struggles": [self._struggle("n/a", fix="none")]})
        r = self._records()[0]
        self.assertEqual(len(r["struggles"]), 1)
        self.assertNotIn("guard", r)


    def test_guard_catches_uppercase_na_and_survives_bad_inbox_lines(self):
        inbox = os.environ["EPISODIC_INBOX"]
        os.makedirs(inbox, exist_ok=True)
        with open(os.path.join(inbox, "old.jsonl"), "w") as fh:
            fh.write('7\n{"struggles": "x"}\n')
        self.assertTrue(np_capture.append_note({"session_id": "s", "struggles": [
            self._struggle("N/A", fix="restart the runner and retry the build")]}))
        r = [x for x in self._records() if isinstance(x, dict) and x.get("session_id") == "s"][0]
        self.assertEqual(r["struggles"], [])


    def _strategy(self, title, content="split the change so each unit plans against fresh state"):
        return {"title": title, "description": "d", "content": content, "topic_triggers": ["x"]}

    def test_guard_length_boundaries(self):
        ok_long = "a " * 999 + "b"           # 1999 chars of symptom
        rec = {"struggles": [
            self._struggle(ok_long, fix="z"),             # 2001 chars with the fix, too long
            self._struggle(ok_long[:-2], fix="z"),        # 1999 chars with the fix, kept
            self._struggle("c " * 998 + "cc", fix="z"),   # exactly 2000 chars, kept
            self._struggle("abcdefghi", fix="jklmnopqr"),  # normalized key 19 chars, too short
            self._struggle("abcdefghi", fix="jklmnopqrs"), # 20 chars, kept
        ]}
        np_capture.append_note(rec)
        r = self._records()[0]
        self.assertEqual(len(r["struggles"]), 3)
        self.assertEqual(sorted(d["reason"] for d in r["guard"]["dropped"]), ["too-long", "too-short"])

    def test_guard_applies_to_strategies_and_keeps_kept_items_whole(self):
        good = self._strategy("Split the change by plan unit")
        np_capture.append_note({"strategies": [good, dict(good), self._strategy("TBD", content="tbd")]})
        r = self._records()[0]
        self.assertEqual(r["strategies"], [good])
        self.assertEqual(sorted(d["reason"] for d in r["guard"]["dropped"]), ["duplicate", "junk"])

    def test_guard_dedups_a_secret_bearing_item_against_its_scrubbed_copy(self):
        s = self._struggle("leaked token ghp_ABCDEFGHIJKLMNOPQRSTU in a log line")
        np_capture.append_note({"session_id": "a", "struggles": [s]})
        np_capture.append_note({"session_id": "b", "struggles": [dict(s)]})
        recs = self._records()
        self.assertEqual(len(recs[0]["struggles"]), 1)
        self.assertEqual(recs[1]["struggles"], [])

    def test_guard_dropped_text_is_truncated_and_scrubbed(self):
        junk = self._struggle("none", fix="token ghp_ABCDEFGHIJKLMNOPQRSTU " + "y" * 200)
        np_capture.append_note({"struggles": [junk]})
        inbox = os.environ["EPISODIC_INBOX"]
        with open(os.path.join(inbox, os.listdir(inbox)[0]), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("ghp_ABCDEFG", raw)
        self.assertLessEqual(len(self._records()[0]["guard"]["dropped"][0]["text"]), 80)

    def test_guard_tolerates_odd_shapes(self):
        rec = {"session_id": "s", "struggles": "not a list", "strategies": [7, None, "x"]}
        self.assertTrue(np_capture.append_note(rec))
        r = self._records()[0]
        self.assertEqual(r["struggles"], "not a list")
        self.assertEqual(r["strategies"], [])

    def test_guard_leaves_a_record_without_items_untouched(self):
        np_capture.append_note({"session_id": "s", "headline": "h"})
        self.assertEqual(self._records()[0], {"session_id": "s", "headline": "h"})

    def test_guard_runs_inside_capture_end_to_end(self):
        note = json.dumps({"headline": "h", "body": "b", "candidate_topics": [], "keywords": [],
                           "struggles": [self._struggle("n/a", fix="none"),
                                         self._struggle("CI job hung for six hours with no timeout set")],
                           "strategies": []})
        with mock.patch.object(np_capture.np_model, "complete", return_value=note):
            np_capture.capture(self._payload(), mode="session-end")
        r = self._records()[0]
        self.assertEqual(len(r["struggles"]), 1)
        self.assertEqual(r["guard"]["dropped"][0]["reason"], "junk")
        self.assertTrue(os.listdir(os.environ["EPISODIC_SEEN_DIR"]))


    def test_guard_scrubs_a_secret_that_straddles_the_audit_cut(self):
        junk = self._struggle("none", fix="y" * 66 + " ghp_ABCDEFGHIJKLMNOPQRSTU tail")
        np_capture.append_note({"struggles": [junk]})
        inbox = os.environ["EPISODIC_INBOX"]
        with open(os.path.join(inbox, os.listdir(inbox)[0]), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("ghp_", raw)

    def test_guard_junk_in_any_core_field_drops_the_item(self):
        # A struggle with a real symptom but no fix teaches nothing, so it is dropped.
        np_capture.append_note({"struggles": [
            self._struggle("CI job hung for six hours with no timeout set", fix="none")]})
        r = self._records()[0]
        self.assertEqual(r["struggles"], [])
        self.assertEqual(r["guard"]["dropped"][0]["reason"], "junk")


if __name__ == "__main__":
    unittest.main()
