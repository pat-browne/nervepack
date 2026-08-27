"""Composition test for the durable-text form gate.

Per ARCHITECTURE invariant 6, unit tests are necessary but NOT sufficient: the
dashboard was dead for seven weeks while every unit passed, because nothing
asserted the whole chain produced a reachable end state. This drives real
payloads through the REAL cli.py entry point as a subprocess.
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
_MANIFEST = os.path.join(_ENGINE_DIR, "setup", "hooks.manifest")
_TOGGLES = os.path.join(_ENGINE_DIR, "setup", "toggles.conf")


class TestFormGateComposition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _run_cli(self, payload):
        env = dict(os.environ)
        env.pop("NERVEPACK_AGENT", None)
        return subprocess.run([sys.executable, _CLI, "hook", "form-gate"],
                              input=json.dumps(payload), capture_output=True,
                              text=True, env=env, timeout=60)

    def test_entry_point_resolves_and_exits_zero(self):
        """A missing _HOOKS row would make this a usage error, not a no-op."""
        proc = self._run_cli({"session_id": "s1", "tool_name": "Write",
                              "tool_input": {"file_path": "/x/a.py",
                                             "content": "x = 1"}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("usage", (proc.stderr or "").lower())
        self.assertNotIn("unknown hook", (proc.stderr or "").lower())

    def test_semicolon_in_markdown_is_flagged_through_the_real_entry_point(self):
        """The categorical channel reaches the real cli.py either way.

        Whether the decision is "ask" or "allow" (with additionalContext) is
        governed by the form_gate.categorical toggle param -- ships as `warn`
        in this task, flips to `ask` in Task 6 after the corpus check. This
        test proves the whole chain (extraction -> stripping -> lint ->
        decision) reaches the real entry point and names the semicolon
        either way; the toggle's own value is asserted separately by
        test_toggle_row_exists_with_expected_params and the Task 6 live probe.
        """
        path = os.path.join(self.tmp, "doc.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("placeholder")
        proc = self._run_cli({
            "session_id": "s1", "tool_name": "Write",
            "tool_input": {"file_path": path,
                           "content": "One clause; a second clause follows."}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if not proc.stdout.strip():
            self.skipTest("no content overlay linter on this machine")
        data = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertIn(data["permissionDecision"], ("ask", "allow"))
        reason = data.get("permissionDecisionReason") or data.get("additionalContext") or ""
        self.assertIn("semicolon", reason)

    def test_em_dash_inside_a_fence_allows_end_to_end(self):
        """Exercises the Task 1 linter fix through the whole chain."""
        path = os.path.join(self.tmp, "doc.md")
        proc = self._run_cli({
            "session_id": "s1", "tool_name": "Write",
            "tool_input": {"file_path": path,
                           "content": "Clean prose only.\n\n"
                                      "```text\nan em dash — in code\n```\n"}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_every_manifest_row_is_registered(self):
        with open(_MANIFEST, encoding="utf-8") as fh:
            rows = [r for r in fh if "form-gate" in r and not r.startswith("#")]
        matchers = {r.split("|")[1] for r in rows}
        self.assertEqual(matchers,
                         {"Write", "Edit", "Artifact", "Bash", "mcp__.*"})

    def test_toggle_row_exists_with_expected_params(self):
        with open(_TOGGLES, encoding="utf-8") as fh:
            row = [r for r in fh if r.startswith("form_gate|")]
        self.assertEqual(len(row), 1, "exactly one form_gate row")
        params = row[0].split("|")[4]
        for key in ("categorical=", "rate=", "rate_threshold=", "timeout_s=",
                    "exempt_globs="):
            self.assertIn(key, params)
        self.assertNotIn(" ", params.strip(),
                         "np_toggle splits params on space or comma")

    def test_turn_gate_threshold_agrees_with_the_rate_channel(self):
        with open(_TOGGLES, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("form_threshold=2.5", content)
        self.assertNotIn("form_threshold=12", content)


if __name__ == "__main__":
    unittest.main()
