#!/usr/bin/env python3
"""Contract test for np-eval-signals.py (stdlib unittest — no pytest dependency,
per the harness language policy in CLAUDE.md). Black-box: runs the script as a
subprocess and asserts on its JSON, so it guards the same interface np-evaluator.sh
calls. Run: `python3 test_signals.py` (or `python3 -m unittest`)."""
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SIG = os.path.join(HERE, "..", "..", "np-eval-signals.py")


class TestSignals(unittest.TestCase):
    def test_counts_and_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "toggles.conf")
            with open(conf, "w") as fh:
                fh.write("directive|shared|runtime|on|\n")
            sig_dir = os.path.join(tmp, "sig")
            os.makedirs(sig_dir)
            with open(os.path.join(sig_dir, "s1.log"), "w") as fh:
                # lesson-recall is the merged hook (replaces playbook-recall +
                # strategy-recall, which no longer exist) — two firings here
                # prove count_markers actually counts the lesson-recall prefix.
                fh.write("lesson-guard ask nuke\nlesson-recall\n"
                         "episodic-recall\nlesson-recall\n")
            transcript = os.path.join(tmp, "t.jsonl")
            with open(transcript, "w") as fh:
                fh.write('{"type":"tool_use","name":"Bash"}\n')
                fh.write('{"type":"tool_use","name":"Skill","input":{"skill":"np-kb-branding"}}\n')

            env = dict(os.environ)
            env.update(
                NP_TOGGLES_CONF=conf,
                NP_TOGGLES_LOCAL=os.path.join(tmp, "local"),
                NP_SIGNAL_DIR=sig_dir,
            )
            out = subprocess.run(
                ["python3", SIG, "s1", transcript],
                env=env, capture_output=True, text=True, check=True,
            ).stdout
            sig = json.loads(out)

            self.assertEqual(sig["playbook_fires"], 1)
            # 2 lesson-recall firings + 1 episodic-recall firing.
            self.assertEqual(sig["recall_injections"], 3)
            self.assertEqual(sig["tool_calls"], 2)
            self.assertTrue(sig["directive_present"])
            self.assertGreater(sig["directive_tokens"], 0)  # fixed injection overhead measured
            self.assertIn("np-kb-branding", sig["skills_invoked"])

    def test_directive_off_resolves_bashfree(self):
        # Phase 12: directive_present() resolves via np_toggle IN-PROCESS (no bash).
        # Prove it reads the conf to return False when the toggle is OFF, and that it
        # needs no bash -- NP_BASH points at a nonexistent path, so any lingering
        # ["bash", ...] shell-out would error and (fail-open) wrongly report True.
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "toggles.conf")
            with open(conf, "w") as fh:
                fh.write("directive|shared|runtime|off|\n")
            sig_dir = os.path.join(tmp, "sig")
            os.makedirs(sig_dir)
            transcript = os.path.join(tmp, "t.jsonl")
            with open(transcript, "w") as fh:
                fh.write('{"type":"tool_use","name":"Bash"}\n')
            env = dict(os.environ)
            env.update(
                NP_TOGGLES_CONF=conf,
                NP_TOGGLES_LOCAL=os.path.join(tmp, "local"),
                NP_SIGNAL_DIR=sig_dir,
                NP_BASH=os.path.join(tmp, "no-such-bash-xyz"),
            )
            sig = json.loads(subprocess.run(
                ["python3", SIG, "s1", transcript],
                env=env, capture_output=True, text=True, check=True,
            ).stdout)
            self.assertFalse(sig["directive_present"])

    def test_tokens_summed_once_per_message_id(self):
        # Claude Code logs one line per content block of a turn, all sharing the
        # same message.id + usage object. Summing every line triple-counts; the
        # extractor must dedup by id. Two lines for m1 (must count once) + one m2.
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "toggles.conf")
            with open(conf, "w") as fh:
                fh.write("directive|shared|runtime|on|\n")
            u1 = ('{"type":"assistant","message":{"id":"m1","usage":'
                  '{"input_tokens":50,"output_tokens":100,'
                  '"cache_read_input_tokens":1000,"cache_creation_input_tokens":200}}}\n')
            transcript = os.path.join(tmp, "t.jsonl")
            with open(transcript, "w") as fh:
                fh.write(u1)      # m1 first content block
                fh.write(u1)      # m1 second content block — same id, must NOT re-add
                fh.write('{"type":"assistant","message":{"id":"m2","usage":'
                         '{"input_tokens":5,"output_tokens":30,'
                         '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n')
                fh.write('{"type":"user","message":{"content":"no usage here"}}\n')
            env = dict(os.environ)
            env.update(
                NP_TOGGLES_CONF=conf,
                NP_TOGGLES_LOCAL=os.path.join(tmp, "local"),
                NP_SIGNAL_DIR=os.path.join(tmp, "sig"),
            )
            sig = json.loads(subprocess.run(
                ["python3", SIG, "s1", transcript],
                env=env, capture_output=True, text=True, check=True,
            ).stdout)
            tk = sig["tokens"]
            self.assertEqual(tk["output"], 130)          # 100 (once) + 30
            self.assertEqual(tk["input"], 55)            # 50 (once) + 5
            self.assertEqual(tk["cache_read"], 1000)     # m1 counted once
            self.assertEqual(tk["cache_creation"], 200)
            self.assertEqual(tk["total"], 130 + 55 + 1000 + 200)

    def test_struggles_counted_from_episodic_inbox(self):
        # struggles is NOT in the transcript/signal-log; the real data lives in the
        # episodic inbox (capture writes it before the evaluator runs). Match by
        # session_id and count struggles[]; take the max across duplicate captures.
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "toggles.conf")
            with open(conf, "w") as fh:
                fh.write("directive|shared|runtime|on|\n")
            ep = os.path.join(tmp, "ep-inbox")
            os.makedirs(ep)
            with open(os.path.join(ep, "2026-06-08.jsonl"), "w") as fh:
                # a checkpoint capture (1 struggle) then the session-end capture (2)
                fh.write(json.dumps({"session_id": "s1", "struggles": [{"symptom": "x"}]}) + "\n")
                fh.write(json.dumps({"session_id": "s1",
                                     "struggles": [{"symptom": "x"}, {"symptom": "y"}]}) + "\n")
                fh.write(json.dumps({"session_id": "other", "struggles": [{"a": 1}]}) + "\n")
            env = dict(os.environ)
            env.update(
                NP_TOGGLES_CONF=conf,
                NP_TOGGLES_LOCAL=os.path.join(tmp, "local"),
                NP_SIGNAL_DIR=os.path.join(tmp, "sig"),
                EPISODIC_INBOX=ep,
            )
            sig = json.loads(subprocess.run(
                ["python3", SIG, "s1", os.path.join(tmp, "absent.jsonl")],
                env=env, capture_output=True, text=True, check=True,
            ).stdout)
            self.assertEqual(sig["struggles"], 2)            # max(1, 2), other session ignored

    def test_playbook_heeded_gated_but_not_executed(self):
        # heeded = a guard fired for a command that did NOT subsequently run.
        # The guard logs a fingerprint of the gated command; signals fingerprints
        # the executed Bash commands from the transcript. gated - executed = heeded.
        import hashlib

        def fp(cmd):
            return hashlib.sha256(" ".join(cmd.split()).encode("utf-8")).hexdigest()[:16]

        cmd_ran = "git reset --hard origin/main"      # gated AND then executed -> NOT heeded
        cmd_avoided = "rm -rf /important/dir"          # gated, never executed   -> heeded
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "toggles.conf")
            with open(conf, "w") as fh:
                fh.write("directive|shared|runtime|on|\n")
            sig_dir = os.path.join(tmp, "sig")
            os.makedirs(sig_dir)
            with open(os.path.join(sig_dir, "s1.log"), "w") as fh:
                fh.write(f"lesson-guard warn nuke :: {fp(cmd_ran)}\n")
                fh.write(f"lesson-guard ask nuke :: {fp(cmd_avoided)}\n")
            transcript = os.path.join(tmp, "t.jsonl")
            with open(transcript, "w") as fh:
                fh.write(json.dumps({"type": "assistant", "message": {"id": "m1", "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": cmd_ran}}]}}) + "\n")
            env = dict(os.environ)
            env.update(NP_TOGGLES_CONF=conf, NP_TOGGLES_LOCAL=os.path.join(tmp, "local"),
                       NP_SIGNAL_DIR=sig_dir)
            sig = json.loads(subprocess.run(
                ["python3", SIG, "s1", transcript],
                env=env, capture_output=True, text=True, check=True,
            ).stdout)
            self.assertEqual(sig["playbook_fires"], 2)
            self.assertEqual(sig["playbook_heeded"], 1)   # only the avoided one

    def test_missing_log_and_transcript_fail_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "toggles.conf")
            with open(conf, "w") as fh:
                fh.write("directive|shared|runtime|on|\n")
            env = dict(os.environ)
            env.update(
                NP_TOGGLES_CONF=conf,
                NP_TOGGLES_LOCAL=os.path.join(tmp, "local"),
                NP_SIGNAL_DIR=os.path.join(tmp, "sig"),
            )
            out = subprocess.run(
                ["python3", SIG, "nope", os.path.join(tmp, "absent.jsonl")],
                env=env, capture_output=True, text=True, check=True,
            ).stdout
            sig = json.loads(out)
            self.assertEqual(sig["playbook_fires"], 0)
            self.assertEqual(sig["recall_injections"], 0)
            self.assertEqual(sig["tool_calls"], 0)
            self.assertEqual(sig["skills_invoked"], [])
            self.assertEqual(
                sig["tokens"],
                {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "total": 0},
            )


if __name__ == "__main__":
    unittest.main()
