#!/usr/bin/env python3
"""Port of toggles/test_audit.sh + test_audit_clean.sh (phase 14) — np_toggle_audit,
now the audit engine behind `cli.py toggle audit`. Ports the drift-flagged and
clean-install assertions AND adds the phase-14 cli.py-form cases (the real post-13
install): a clean install of cli.py-dispatched hooks must audit OK; an unknown
`cli.py hook widget-thing` must flag UNMANAGED; session-flush (always-on infra) is
ignored. Hermetic: settings via CLAUDE_SETTINGS, features via NP_TOGGLES_CONF,
crontab injected (never reads the dev box's real cron). stdlib unittest, zero-dep."""
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)

import np_toggle_audit  # noqa: E402


class TestToggleAudit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.conf = os.path.join(self.tmp, "toggles.conf")
        self.settings = os.path.join(self.tmp, "settings.json")
        self._prev = os.environ.get("NP_TOGGLES_CONF")
        os.environ["NP_TOGGLES_CONF"] = self.conf

    def tearDown(self):
        self._tmp.cleanup()
        if self._prev is None:
            os.environ.pop("NP_TOGGLES_CONF", None)
        else:
            os.environ["NP_TOGGLES_CONF"] = self._prev

    def _conf(self, text):
        with open(self.conf, "w", newline="") as fh:
            fh.write(text)

    def _settings(self, obj):
        with open(self.settings, "w") as fh:
            json.dump(obj, fh)

    def _audit(self, crontab=""):
        buf = io.StringIO()
        code = np_toggle_audit.run(settings_path=self.settings,
                                   crontab_fn=lambda: crontab, out=buf)
        return code, buf.getvalue()

    # --- drift (bash test_audit.sh) ----------------------------------------
    def test_flags_unmanaged_sh_hook(self):
        self._conf("memory|shared|runtime|on|\n")
        self._settings({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command",
             "command": "~/Code/nervepack/setup/widget-guard.sh"}]}]}})
        code, out = self._audit()
        self.assertIn("widget-guard", out)
        self.assertEqual(code, 1)

    # --- clean (bash test_audit_clean.sh, .sh forms) -----------------------
    def test_clean_install_sh_forms_ok(self):
        self._conf("memory|shared|runtime|on|\nlessons|shared|runtime|on|\n"
                   "evaluator|shared|runtime|on|\ndirective|shared|runtime|on|\n"
                   "sync|shared|runtime|on|\n")
        base = "~/Code/nervepack/engine/setup/"
        self._settings({"hooks": {
            "SessionStart": [{"matcher": "", "hooks": [{"type": "command",
                "command": base + "nervepack-session-directive.sh"}]}],
            "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command",
                "command": base + "episodic-recall.sh"}]}],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command",
                    "command": base + "lesson-guard.sh"}]},
                {"matcher": "", "hooks": [{"type": "command",
                    "command": base + "60-generate-index.sh"}]}],
        }})
        code, out = self._audit()
        self.assertNotIn("UNMANAGED", out)
        self.assertIn("OK: all Nervepack hooks/cron map to a toggle family", out)
        self.assertEqual(code, 0)

    # --- clean (phase-14 cli.py forms — the real post-13 install) ----------
    def test_clean_install_cli_forms_ok(self):
        self._conf("memory|shared|runtime|on|\nlessons|shared|runtime|on|\n"
                   "directive|shared|runtime|on|\nevaluator|shared|runtime|on|\n"
                   "skills|shared|runtime|on|\nresume|shared|runtime|on|\n"
                   "focus|shared|runtime|on|\nmaintain|shared|runtime|on|\n"
                   "sync|shared|runtime|on|\n")
        cli = "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py "
        self._settings({"hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook session-directive"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook session-flush"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook backcapture-sweep &"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook resume-sessionstart &"}]}],
            "UserPromptSubmit": [
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook lesson-recall"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook episodic-recall"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook resume-recall"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook skill-trigger-recall"}]}],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": cli + "hook lesson-guard"}]}],
            "SessionEnd": [
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook episodic-capture SessionEnd"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook evaluator"}]}],
        }})
        # cli.py-dispatched crons too (the aggregator maps to evaluator, maintain crons to maintain)
        cron = ("*/1 * * * * " + cli + "cron aggregate-metrics\n"
                "0 8 * * * " + cli + "cron memory-promote\n"
                "0 9 * * * " + cli + "cron refine\n")
        code, out = self._audit(crontab=cron)
        self.assertNotIn("UNMANAGED", out)
        self.assertIn("OK: all Nervepack hooks/cron map to a toggle family", out)
        self.assertEqual(code, 0)

    def test_flags_unknown_cli_hook(self):
        self._conf("memory|shared|runtime|on|\n")
        cli = "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py "
        self._settings({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": cli + "hook widget-thing"}]}]}})
        code, out = self._audit()
        self.assertIn("UNMANAGED: widget-thing", out)
        self.assertEqual(code, 1)

    def test_session_flush_never_flagged(self):
        # session-flush is always-on infra with no toggle: even with NO family it
        # must be ignored, not flagged.
        self._conf("memory|shared|runtime|on|\n")
        cli = "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py "
        self._settings({"hooks": {"SessionStart": [
            {"matcher": "", "hooks": [{"type": "command", "command": cli + "hook session-flush"}]}]}})
        code, out = self._audit()
        self.assertNotIn("session-flush", out)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
