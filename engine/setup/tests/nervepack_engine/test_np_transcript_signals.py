# np-test: episodic signal pre-pass | happy
"""Tests for np_transcript_signals: the deterministic friction pre-pass that runs
before the capture model distills struggles."""
import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "nervepack_engine"))
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import np_transcript_signals as sig  # noqa: E402


def _user(text, source="typed"):
    return {"type": "user", "promptSource": source,
            "message": {"role": "user", "content": text}}


def _use(tid, name, inp=None):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp or {}}]}}


def _result(tid, text, error=False):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": error}]}}


class TestSignals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "sid.jsonl")

    def _write(self, records, path=None):
        with open(path or self.path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def _cats(self, out):
        return [(e["category"], e["line"]) for e in out["friction"]]

    def test_human_turn_and_interrupt(self):
        self._write([_user("fix the bug"), _user("[Request interrupted by user]"),
                     _user("<system-reminder>x</system-reminder>")])
        out = sig.collect(self.path)
        self.assertEqual(self._cats(out), [("human_turn", 1), ("human_interrupt", 2)])
        self.assertEqual(out["friction"][0]["file"], "sid.jsonl")

    def test_question_to_human(self):
        self._write([_use("a", "AskUserQuestion", {"questions": [{"question": "Which db?"}]}),
                     _use("b", "mcp__ccd_turn__wrap_up", {"ask": "Ship it?"})])
        out = sig.collect(self.path)
        self.assertEqual([e["category"] for e in out["friction"]], ["question_to_human"] * 2)
        self.assertIn("Which db?", out["friction"][0]["excerpt"])

    def test_error_kinds_split(self):
        self._write([
            _use("1", "Bash"), _result("1", "Permission to use Bash has been denied.", True),
            _use("2", "Bash"), _result("2", "PreToolUse:Bash hook error: blocked by policy", True),
            _use("3", "Bash"), _result("3", "exit code 1: no such file", True),
        ])
        cats = [e["category"] for e in sig.collect(self.path)["friction"]]
        self.assertEqual(cats, ["permission_denied", "hook_block", "tool_error"])

    def test_error_paired_with_later_success_and_attempts(self):
        self._write([
            _use("1", "Edit"), _result("1", "old_string not found", True),
            _use("2", "Edit"), _result("2", "old_string not found", True),
            _use("3", "Edit"), _result("3", "ok"),
            _use("4", "Grep"), _result("4", "regex parse error", True),
        ])
        errs = sig.collect(self.path)["friction"]
        self.assertEqual([(e["tool"], e["later_succeeded"], e["attempts"]) for e in errs],
                         [("Edit", True, 3), ("Edit", True, 2), ("Grep", False, 1)])

    def test_blocked_result_and_repeated_skill(self):
        self._write([
            _use("1", "Bash"), _result("1", '{"status": "blocked", "why": "gate"}'),
            _use("2", "Skill", {"skill": "x"}), _use("3", "Skill", {"skill": "x"}),
            _use("4", "Read"), _result("4", '"status": "blocked" in a doc'),
        ])
        cats = [e["category"] for e in sig.collect(self.path)["friction"]]
        self.assertEqual(cats, ["blocked_result", "repeated_skill"])

    def test_subagent_files_read_without_human_turns(self):
        sub = os.path.join(self.tmp, "sid", "subagents")
        os.makedirs(sub)
        self._write([_user("dispatch prompt"), _use("1", "Bash"), _result("1", "boom", True)],
                    os.path.join(sub, "agent-a.jsonl"))
        self._write([_user("hi")])
        out = sig.collect(self.path)
        self.assertEqual([(e["category"], e["file"]) for e in out["friction"]],
                         [("human_turn", "sid.jsonl"), ("tool_error", "agent-a.jsonl")])

    def test_missing_or_garbage_fails_open(self):
        self.assertEqual(sig.collect(os.path.join(self.tmp, "nope.jsonl")), {"friction": []})
        with open(self.path, "w") as fh:
            fh.write("not json\n[1]\n")
        self.assertEqual(sig.collect(self.path), {"friction": []})

    def test_render_and_anchors(self):
        self._write([_use("1", "Bash"), _result("1", "boom", True), _user("stop that")])
        out = sig.collect(self.path)
        text = sig.render(out)
        self.assertIn("sid.jsonl:2 tool_error", text)
        self.assertIn("sid.jsonl:3 human_turn", text)
        self.assertEqual(sig.anchors(out), {"sid.jsonl:2", "sid.jsonl:3"})
        self.assertEqual(sig.render({"friction": []}), "")


if __name__ == "__main__":
    unittest.main()
