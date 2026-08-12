"""Driver-level tests for `cli.py setup install-hooks` (phase 13) -- the single
call path that replaced the 11 NN-install-*.sh hook installers + np-hook-lib.sh.
Runs the real dispatch into a temp CLAUDE_SETTINGS and asserts the full
registration inventory: right command under right event/matcher, session-flush
LAST in SessionEnd, lesson-guard under all six matchers (Bash/Read/Edit/Write/
Skill/mcp__.*), open-artifact matcher Write, backgrounded hooks keep
`>/dev/null 2>&1 &`, idempotency, and 53's
legacy migration purge. Consolidates the retired per-installer .sh tests
(directive/episodic/evaluator/escalation/lessons/session/backcapture/flush).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
_CLI = os.path.join(_ENGINE, "nervepack_engine", "cli.py")


def _cmds(settings, event):
    out = []
    for entry in settings.get("hooks", {}).get(event, []):
        for h in entry.get("hooks", []):
            out.append((entry.get("matcher", ""), h["command"]))
    return out


class TestInstallHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings = os.path.join(self.tmp, "settings.json")
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _install(self, seed=None):
        if seed is not None:
            with open(self.settings, "w") as fh:
                json.dump(seed, fh)
        env = dict(os.environ, CLAUDE_SETTINGS=self.settings)
        # NP_HOOK_WRAP=0 pins the deterministic unwrapped form regardless of kernel.
        env["NP_HOOK_WRAP"] = "0"
        r = subprocess.run([sys.executable, _CLI, "setup", "install-hooks"],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.settings, encoding="utf-8") as fh:
            return json.load(fh)

    def _commands(self, settings, event):
        return [c for _m, c in _cmds(settings, event)]

    def test_full_inventory_present(self):
        s = self._install()
        ss = self._commands(s, "SessionStart")
        self.assertTrue(any("cli.py sync >/dev/null 2>&1 &" in c for c in ss))
        self.assertTrue(any("hook open-dashboard >/dev/null 2>&1 &" in c for c in ss))
        self.assertTrue(any(c.endswith("hook session-directive") for c in ss))
        self.assertTrue(any("hook backcapture-sweep >/dev/null 2>&1 &" in c for c in ss))
        self.assertTrue(any(c.endswith("hook resume-sessionstart &") for c in ss))

        se = self._commands(s, "SessionEnd")
        self.assertTrue(any("cli.py sync exit >/dev/null 2>&1 &" in c for c in se))
        self.assertTrue(any("hook episodic-capture session-end &" in c for c in se))
        self.assertTrue(any(c.endswith("hook evaluator &") for c in se))
        self.assertTrue(any(c.endswith("hook session-flush") for c in se))

        pc = self._commands(s, "PreCompact")
        self.assertTrue(any("hook episodic-capture checkpoint" in c for c in pc))

        ups = self._commands(s, "UserPromptSubmit")
        for name in ("episodic-recall", "lesson-recall", "struggle-escalation",
                     "skill-trigger-recall", "resume-recall"):
            self.assertTrue(any(("hook " + name) in c for c in ups), name)

    def test_session_flush_is_last_in_session_end(self):
        s = self._install()
        se = self._commands(s, "SessionEnd")
        self.assertIn("hook session-flush", se[-1])

    def test_lesson_guard_under_all_matchers(self):
        # issue #152: Phase 2 (non-Bash tool_name matching) never ran for
        # Edit/Write/Skill/MCP tool calls because no PreToolUse matcher told
        # Claude Code to invoke this hook for them -- these six must coexist.
        s = self._install()
        pre = _cmds(s, "PreToolUse")
        guards = sorted(m for m, c in pre if "hook lesson-guard" in c)
        self.assertEqual(guards, ["Bash", "Edit", "Read", "Skill", "Write", "mcp__.*"])

    def test_open_artifact_matcher_is_write(self):
        s = self._install()
        post = _cmds(s, "PostToolUse")
        self.assertTrue(any(m == "Write" and "hook open-artifact" in c for m, c in post))

    def test_backgrounded_hooks_keep_redirect(self):
        s = self._install()
        all_cmds = []
        for event in s.get("hooks", {}):
            all_cmds += self._commands(s, event)
        backgrounded = [c for c in all_cmds if c.rstrip().endswith("&")]
        self.assertGreaterEqual(len(backgrounded), 4)
        # Every `... >/dev/null 2>&1 &` form is intact; the bare ` &` ones
        # (episodic-capture, evaluator, resume-sessionstart) self-manage output.
        for c in backgrounded:
            if ">/dev/null" in c:
                self.assertIn(">/dev/null 2>&1 &", c)

    def test_idempotent(self):
        self._install()
        s = self._install()  # second run
        # No event should carry a duplicate command.
        for event in s.get("hooks", {}):
            cmds = self._commands(s, event)
            # (matcher, command) pairs must be unique within an event
            pairs = _cmds(s, event)
            self.assertEqual(len(pairs), len(set(pairs)), "%s has duplicates: %s" % (event, pairs))

    def test_sync_dedup_does_not_collapse_other_cli_hooks(self):
        # Regression: the top-level `cli.py sync` row must dedup on its full
        # "cli.py sync" tail, NOT the shared "cli.py" filename — otherwise
        # re-registering it would purge every other cli.py-dispatched SessionStart
        # hook (open-dashboard / session-directive / backcapture / resume). After
        # two installs both sync AND all its cli.py siblings must survive exactly once.
        self._install()
        s = self._install()
        ss = self._commands(s, "SessionStart")
        self.assertEqual(sum("cli.py sync >/dev/null" in c for c in ss), 1)
        for sibling in ("hook open-dashboard", "hook session-directive",
                        "hook backcapture-sweep", "hook resume-sessionstart"):
            self.assertEqual(sum(sibling in c for c in ss), 1, sibling)

    def test_legacy_purge_migration(self):
        # A pre-merge settings.json with playbook-guard/playbook-recall/
        # strategy-recall must migrate cleanly to the lessons layer.
        seed = {"hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command",
                 "command": "~/Code/nervepack/engine/setup/playbook-guard.sh"}]},
            ],
            "UserPromptSubmit": [
                {"matcher": "", "hooks": [{"type": "command",
                 "command": "~/Code/nervepack/engine/setup/playbook-recall.sh"}]},
                {"matcher": "", "hooks": [{"type": "command",
                 "command": "~/Code/nervepack/engine/setup/strategy-recall.sh"}]},
            ],
        }}
        s = self._install(seed=seed)
        blob = json.dumps(s)
        for stale in ("playbook-guard.sh", "playbook-recall.sh", "strategy-recall.sh"):
            self.assertNotIn(stale, blob, stale)
        pre = _cmds(s, "PreToolUse")
        self.assertEqual(sorted(m for m, c in pre if "hook lesson-guard" in c),
                          ["Bash", "Edit", "Read", "Skill", "Write", "mcp__.*"])
        ups = self._commands(s, "UserPromptSubmit")
        self.assertEqual(sum(1 for c in ups if "hook lesson-recall" in c), 1)

    def test_legacy_purge_migration_sync_script(self):
        # Phase 17 retired 40-sync-nervepack.sh for np_sync.py (`cli.py sync`).
        # A settings.json registered before that phase must migrate cleanly:
        # the old script-based SessionStart/SessionEnd entries gone, replaced
        # by exactly one `cli.py sync` entry each -- no leftover duplicate that
        # silently no-ops (dead script) every session.
        seed = {"hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command",
                 "command": "~/Code/nervepack/engine/setup/40-sync-nervepack.sh >/dev/null 2>&1 &"}]},
            ],
            "SessionEnd": [
                {"matcher": "", "hooks": [{"type": "command",
                 "command": "~/Code/nervepack/engine/setup/40-sync-nervepack.sh exit >/dev/null 2>&1 &"}]},
            ],
        }}
        s = self._install(seed=seed)
        blob = json.dumps(s)
        self.assertNotIn("40-sync-nervepack.sh", blob)
        ss = self._commands(s, "SessionStart")
        se = self._commands(s, "SessionEnd")
        self.assertEqual(sum("cli.py sync >/dev/null" in c for c in ss), 1)
        self.assertEqual(sum("cli.py sync exit >/dev/null" in c for c in se), 1)

    def test_every_hook_name_dispatches_to_a_real_handler(self):
        # Non-vacuity for the glob-coverage guard: every `cli.py hook <name>` in
        # the manifest must map to a registered handler in cli.py's _HOOKS.
        sys.path.insert(0, os.path.join(_ENGINE, "nervepack_engine"))
        sys.path.insert(0, _ENGINE)
        import importlib
        cli = importlib.import_module("nervepack_engine.cli")
        import np_hook
        seen = set()
        for _event, _matcher, command in np_hook.read_manifest():
            import re
            m = re.search(r"cli\.py hook ([\w-]+)", command)
            if m:
                seen.add(m.group(1))
        self.assertTrue(seen)
        for name in seen:
            self.assertIn(name, cli._HOOKS, "manifest hook %s has no handler" % name)


if __name__ == "__main__":
    unittest.main()
