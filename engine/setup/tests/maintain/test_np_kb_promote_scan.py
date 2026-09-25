# np-test: kb-promote-scan | toggle/backend/re-entrancy gating, prompt contract,
#          and dispatch wiring for np_agentic_cron.kb_promote_scan().
"""Mirrors test_np_compact.py's gating tests. The agent's own worktree/PR steps
live in the prompt, so this also pins the prompt's hard rules."""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.abspath(os.path.join(HERE, "..", ".."))  # engine/setup
REPO = os.path.abspath(os.path.join(SETUP, "..", ".."))
for _p in (SETUP, os.path.join(SETUP, "..", "nervepack_engine")):
    _p = os.path.normpath(_p)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_agentic_cron  # noqa: E402

PROMPT_BODY = "# kb-promote-scan\n\nMetadata.\n\n## Prompt\n\nRun the scan.\n"
_ENV_KEYS = ("NERVEPACK_AGENT", "CLAUDE_BIN", "NP_LLM_AGENT_CMD", "NP_LLM_BACKEND",
             "KB_PROMOTE_SCAN_LOG")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class GatingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "np")
        _write(os.path.join(self.np, "agents", "np-flow-kb-promote-scan.md"), PROMPT_BODY)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.local = os.path.join(self.tmp, "toggles.local")
        conf = os.path.join(self.tmp, "toggles.conf")
        _write(conf, "maintain.kb_promote_scan|shared|runtime|on|\n")
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home, "NP_TOGGLES_CONF": conf, "NP_TOGGLES_LOCAL": self.local})
        self.env.start()
        self.np_patch = mock.patch.object(np_agentic_cron, "_NP", self.np)
        self.np_patch.start()

    def tearDown(self):
        self.np_patch.stop()
        self.env.stop()

    def _log(self):
        p = os.path.join(self.home, ".cache", "nervepack", "kb-promote-scan.log")
        return open(p, encoding="utf-8").read() if os.path.isfile(p) else ""

    def test_toggle_off_skips(self):
        _write(self.local, "maintain.kb_promote_scan=off\n")
        self.assertEqual(np_agentic_cron.kb_promote_scan(),
                         "skipped: maintain.kb_promote_scan disabled")

    def test_default_on_proceeds_past_gate(self):
        with mock.patch.dict(os.environ, {"CLAUDE_BIN": os.path.join(self.tmp, "nope")}):
            self.assertEqual(np_agentic_cron.kb_promote_scan(),
                             "skipped: claude CLI not found")
        self.assertIn("claude CLI not found", self._log())

    def test_reentrancy_bails_without_log(self):
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            self.assertEqual(np_agentic_cron.kb_promote_scan(),
                             "skipped: NERVEPACK_AGENT already set (re-entrant)")
        self.assertEqual(self._log(), "")

    def test_runs_agent_in_engine_with_extracted_prompt(self):
        claude = os.path.join(self.tmp, "claude")
        _write(claude, "#!/usr/bin/env bash\ntrue\n")
        os.chmod(claude, 0o755)
        with mock.patch.dict(os.environ, {"CLAUDE_BIN": claude}), \
                mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                                  return_value=True) as run:
            self.assertEqual(np_agentic_cron.kb_promote_scan(), "ok: agent run completed")
        prompt = run.call_args[0][0]
        self.assertEqual(prompt.strip(), "Run the scan.")
        self.assertEqual(run.call_args[1]["cwd"], self.np)
        self.assertIn("=== kb-promote-scan run ===", self._log())


class PromptContractTest(unittest.TestCase):
    """The real prompt carries the rules the scheduled agent must follow."""

    def setUp(self):
        path = os.path.join(REPO, "agents", "np-flow-kb-promote-scan.md")
        self.prompt = np_agentic_cron._base_prompt(path)

    def test_prompt_rules(self):
        for needle in ("harness-promote-scan", "pr-review", "origin/trunk",
                       "kb/promote-scan-$DATE", "no promotable content",
                       "Committed by Claude Code", "AI-assisted PR",
                       "gh pr checks", "alarm 900", "Never merge",
                       "PHASE cleanup", "Remove the",
                       "docs/reviews/queue.md",
                       "$HOME/Code/nervepack:$HOME/Code/nervepack-content"):
            self.assertIn(needle, self.prompt)


class WiringTest(unittest.TestCase):
    def test_standalone_and_cli_dispatch(self):
        self.assertIs(np_agentic_cron._STANDALONE_ENTRYPOINTS["kb-promote-scan"],
                      np_agentic_cron.kb_promote_scan)
        import cli
        self.assertIs(cli._CRONS["kb-promote-scan"], np_agentic_cron.kb_promote_scan)


if __name__ == "__main__":
    unittest.main()
