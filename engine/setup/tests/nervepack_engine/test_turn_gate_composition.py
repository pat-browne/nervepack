"""Composition test for the turn-completion gate.

Per ARCHITECTURE invariant 6, unit tests are necessary but NOT sufficient: the
dashboard was dead for seven weeks while every unit passed, because nothing
asserted the whole chain produced a reachable end state. This drives a real
transcript through the REAL cli.py entry point as a subprocess and asserts the
user-visible result -- exit code and stdout JSON.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
_CLI = os.path.join(_ENGINE_DIR, "nervepack_engine", "cli.py")


class TestTurnGateComposition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _transcript(self, records):
        path = os.path.join(self.tmp, "t.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return path

    def _run_cli(self, transcript, stop_hook_active=False):
        payload = json.dumps({"session_id": "s1", "transcript_path": transcript,
                              "stop_hook_active": stop_hook_active,
                              "cwd": self.tmp})
        env = dict(os.environ)
        env.pop("NERVEPACK_AGENT", None)
        proc = subprocess.run([sys.executable, _CLI, "hook", "turn-gate"],
                              input=payload, capture_output=True, text=True,
                              env=env, timeout=30)
        return proc

    def test_ui_edit_without_delivery_blocks_through_the_real_entry_point(self):
        t = self._transcript([
            {"type": "user", "promptSource": "typed",
             "message": {"content": "restyle the button"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/app/Button.tsx"}}]}},
        ])
        proc = self._run_cli(t)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("Button.tsx", data["reason"])

    def test_ui_edit_with_a_screenshot_exits_clean_and_silent(self):
        t = self._transcript([
            {"type": "user", "promptSource": "typed",
             "message": {"content": "restyle the button"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/app/Button.tsx"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result",
                 "content": [{"type": "image", "source": {}}]}]}},
        ])
        proc = self._run_cli(t)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_stop_hook_active_never_blocks(self):
        t = self._transcript([
            {"type": "user", "promptSource": "typed",
             "message": {"content": "go"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/app/a.tsx"}}]}},
        ])
        proc = self._run_cli(t, stop_hook_active=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_unreadable_transcript_exits_zero_and_allows(self):
        proc = self._run_cli(os.path.join(self.tmp, "missing.jsonl"))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_hook_is_registered_in_the_manifest(self):
        manifest = os.path.join(_ENGINE_DIR, "setup", "hooks.manifest")
        with open(manifest, encoding="utf-8") as fh:
            rows = [l for l in fh if l.strip() and not l.startswith("#")]
        stop_rows = [r for r in rows if r.split("|")[0] == "Stop"]
        self.assertTrue(stop_rows, "no Stop row registered")
        self.assertTrue(any("turn-gate" in r for r in stop_rows))
        # A backgrounded gate cannot return a decision.
        self.assertFalse(any(r.rstrip().endswith("&") for r in stop_rows),
                         "the Stop row must not be backgrounded")


if __name__ == "__main__":
    unittest.main()
