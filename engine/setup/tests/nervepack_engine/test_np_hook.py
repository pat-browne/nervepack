"""Tests for np_hook.py -- the stdlib-json port of np-hook-lib.sh (phase 13 of
the bash->Python CLI migration). Ports both bash hook-lib tests 1:1:
tests/toggles/test_hook_lib.sh (register-by-basename idempotency + path
migration + cli-tail dedup + matcher preserved + coexistence) and
tests/toggles/test_hook_lib_win_wrap.sh (the Windows NP_HOOK_WRAP shim), and
adds the (matcher, base) per-matcher-coexistence case that unifies 53's two
lesson-guard matchers into the general register() path.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import np_hook  # noqa: E402


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cmds(settings, event):
    out = []
    for entry in settings.get("hooks", {}).get(event, []):
        for h in entry.get("hooks", []):
            out.append(h["command"])
    return out


def _count(settings, event, substr):
    return sum(1 for c in _cmds(settings, event) if substr in c)


class TestHookBasename(unittest.TestCase):
    def test_cli_tail_wins(self):
        base = np_hook._hook_basename(
            "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook backcapture-sweep >/dev/null 2>&1 &")
        self.assertEqual(base, "nervepack_engine/cli.py hook backcapture-sweep")

    def test_bash_script_basename(self):
        base = np_hook._hook_basename(
            "~/Code/nervepack/engine/setup/40-sync-nervepack.sh >/dev/null 2>&1 &")
        self.assertEqual(base, "40-sync-nervepack.sh")

    def test_no_match_is_empty(self):
        self.assertEqual(np_hook._hook_basename("echo hello"), "")


class TestRegister(unittest.TestCase):
    """1:1 port of tests/toggles/test_hook_lib.sh."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings = os.path.join(self.tmp, "settings.json")
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _reg(self, event, command, matcher="", **kw):
        return np_hook.register(event, command, matcher, settings_path=self.settings, **kw)

    def test_register_and_path_migration(self):
        # old-path entry registered
        self._reg("SessionStart", "~/Code/nervepack/setup/40-sync-nervepack.sh &")
        s = _load(self.settings)
        self.assertEqual(_count(s, "SessionStart", "40-sync-nervepack.sh"), 1)

        # re-run with the NEW (moved) path: must REPLACE, not duplicate.
        self._reg("SessionStart", "~/Code/nervepack/engine/setup/40-sync-nervepack.sh &")
        s = _load(self.settings)
        self.assertEqual(_count(s, "SessionStart", "40-sync-nervepack.sh"), 1)
        self.assertEqual(_count(s, "SessionStart", "engine/setup/40-sync-nervepack.sh"), 1)
        self.assertEqual(_count(s, "SessionStart", "nervepack/setup/40"), 0)

        # idempotent identical re-run
        self._reg("SessionStart", "~/Code/nervepack/engine/setup/40-sync-nervepack.sh &")
        s = _load(self.settings)
        self.assertEqual(_count(s, "SessionStart", "40-sync-nervepack.sh"), 1)

        # a different script in the same event is independent
        self._reg("SessionStart",
                  "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook open-dashboard &")
        s = _load(self.settings)
        self.assertEqual(_count(s, "SessionStart", "hook open-dashboard"), 1)
        self.assertEqual(_count(s, "SessionStart", "40-sync-nervepack.sh"), 1)

    def test_matcher_preserved(self):
        self._reg("PreToolUse", "~/Code/nervepack/engine/setup/playbook-guard.sh", "Bash")
        s = _load(self.settings)
        self.assertEqual(s["hooks"]["PreToolUse"][0]["matcher"], "Bash")

    def test_cli_dispatched_dedup_on_full_tail(self):
        # A CLI-dispatched hook dedups on the FULL "cli.py <group> <name>", not
        # the shared "cli.py" filename -- else every future CLI hook collides.
        self._reg("SessionStart",
                  "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook backcapture-sweep >/dev/null 2>&1 &")
        s = _load(self.settings)
        self.assertEqual(_count(s, "SessionStart", "hook backcapture-sweep"), 1)

        self._reg("SessionStart",
                  "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook lesson-guard >/dev/null 2>&1 &")
        s = _load(self.settings)
        self.assertEqual(_count(s, "SessionStart", "hook backcapture-sweep"), 1)
        self.assertEqual(_count(s, "SessionStart", "hook lesson-guard"), 1)

        # re-registering the first still replaces only itself
        self._reg("SessionStart",
                  "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook backcapture-sweep >/dev/null 2>&1 &")
        s = _load(self.settings)
        self.assertEqual(_count(s, "SessionStart", "hook backcapture-sweep"), 1)
        self.assertEqual(_count(s, "SessionStart", "hook lesson-guard"), 1)

    def test_per_matcher_coexistence(self):
        # 53's unification: the SAME base (cli.py hook lesson-guard) under two
        # different matchers (Bash, Read) must coexist because dedup keys on
        # (matcher, base), not base alone.
        cmd = "python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook lesson-guard"
        self._reg("PreToolUse", cmd, "Bash")
        self._reg("PreToolUse", cmd, "Read")
        s = _load(self.settings)
        self.assertEqual(_count(s, "PreToolUse", "hook lesson-guard"), 2)
        matchers = sorted(e["matcher"] for e in s["hooks"]["PreToolUse"])
        self.assertEqual(matchers, ["Bash", "Read"])
        # idempotent per matcher
        self._reg("PreToolUse", cmd, "Bash")
        s = _load(self.settings)
        self.assertEqual(_count(s, "PreToolUse", "hook lesson-guard"), 2)

    def test_creates_missing_settings(self):
        # No file yet -> register creates it as valid JSON with the entry.
        self.assertFalse(os.path.exists(self.settings))
        self._reg("SessionEnd", "python3 .../cli.py hook session-flush")
        self.assertTrue(os.path.exists(self.settings))
        s = _load(self.settings)
        self.assertEqual(_count(s, "SessionEnd", "session-flush"), 1)

    def test_settings_path_from_env(self):
        env_settings = os.path.join(self.tmp, "env-settings.json")
        with mock.patch.dict(os.environ, {"CLAUDE_SETTINGS": env_settings}):
            np_hook.register("SessionStart", "python3 .../cli.py hook session-directive")
        s = _load(env_settings)
        self.assertEqual(_count(s, "SessionStart", "session-directive"), 1)


class TestWindowsWrap(unittest.TestCase):
    """1:1 port of tests/toggles/test_hook_lib_win_wrap.sh."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings = os.path.join(self.tmp, "settings.json")
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _cmd_at(self):
        return _load(self.settings)["hooks"]["SessionStart"][0]["hooks"][0]["command"]

    def test_wrap_on(self):
        np_hook.register("SessionStart", "~/Code/nervepack/engine/setup/40-sync-nervepack.sh &",
                         settings_path=self.settings, wrap="1")
        self.assertEqual(self._cmd_at(),
                         "bash -lc '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &'")
        # dedup-by-basename still resolves through the wrapper: re-register => one
        np_hook.register("SessionStart", "~/Code/nervepack/engine/setup/40-sync-nervepack.sh &",
                         settings_path=self.settings, wrap="1")
        cmds = _load(self.settings)["hooks"]["SessionStart"]
        self.assertEqual(len(cmds), 1)

    def test_wrap_off_verbatim(self):
        np_hook.register("SessionStart", "~/Code/nervepack/engine/setup/40-sync-nervepack.sh &",
                         settings_path=self.settings, wrap="0")
        self.assertEqual(self._cmd_at(), "~/Code/nervepack/engine/setup/40-sync-nervepack.sh &")

    def test_env_var_forces_wrap(self):
        with mock.patch.dict(os.environ, {"NP_HOOK_WRAP": "1"}):
            np_hook.register("SessionStart", "~/x/y.sh &", settings_path=self.settings)
        self.assertEqual(self._cmd_at(), "bash -lc '~/x/y.sh &'")

    def test_auto_detect_wraps_on_mingw(self):
        # NP_HOOK_WRAP env wins over auto (mirrors bash `${NP_HOOK_WRAP:-auto}`);
        # the runner pins it to 0, so clear it to exercise the uname auto path.
        env = {k: v for k, v in os.environ.items() if k != "NP_HOOK_WRAP"}
        with mock.patch.dict(os.environ, env, clear=True):
            np_hook.register("SessionStart", "~/x/y.sh &", settings_path=self.settings,
                             uname="MINGW64_NT-10.0")
        self.assertEqual(self._cmd_at(), "bash -lc '~/x/y.sh &'")

    def test_auto_detect_verbatim_off_windows(self):
        env = {k: v for k, v in os.environ.items() if k != "NP_HOOK_WRAP"}
        with mock.patch.dict(os.environ, env, clear=True):
            np_hook.register("SessionStart", "~/x/y.sh &", settings_path=self.settings,
                             uname="Linux")
        self.assertEqual(self._cmd_at(), "~/x/y.sh &")

    def test_auto_detect_wraps_when_uname_reports_windows(self):
        # Native-CPython `platform.system()` returns "Windows" (not "MINGW*") even
        # under Git-for-Windows -- the old check left this UNWRAPPED, so the hook
        # command was a bare `.sh &` PowerShell can't run (phase-13 review MAJOR).
        env = {k: v for k, v in os.environ.items() if k != "NP_HOOK_WRAP"}
        with mock.patch.dict(os.environ, env, clear=True):
            np_hook.register("SessionStart", "~/x/y.sh &", settings_path=self.settings,
                             uname="Windows")
        self.assertEqual(self._cmd_at(), "bash -lc '~/x/y.sh &'")

    def test_uname_s_falls_back_to_windows_on_nt(self):
        # When `uname -s` is unreachable (native Windows w/o Git-bash on PATH),
        # _uname_s() returns a "Windows" sentinel iff os.name == "nt" -- the real
        # native-Windows path (uname=None in production), which _wrap then treats
        # as a Windows form. Tested without a live Windows host.
        def _boom(*a, **k):
            raise FileNotFoundError("uname")
        with mock.patch.object(np_hook.subprocess, "run", _boom), \
             mock.patch.object(np_hook.os, "name", "nt"):
            self.assertEqual(np_hook._uname_s(), "Windows")
        with mock.patch.object(np_hook.subprocess, "run", _boom), \
             mock.patch.object(np_hook.os, "name", "posix"):
            self.assertEqual(np_hook._uname_s(), "")

    def test_uname_s_exercises_real_detection(self):
        # Teeth for the auto path: _uname_s() must actually shell to `uname -s`
        # (not a stub) and drive the wrap decision. Assert against whatever this
        # host really is -- POSIX (Linux/Darwin) => verbatim; Git-bash (MINGW*) =>
        # wrapped -- so the test is meaningful on BOTH the Linux and Windows lanes.
        kernel = np_hook._uname_s()
        self.assertTrue(kernel, "_uname_s() returned empty on a real host")
        expect_wrap = kernel.startswith(("MINGW", "MSYS", "CYGWIN", "Windows"))
        env = {k: v for k, v in os.environ.items() if k != "NP_HOOK_WRAP"}
        with mock.patch.dict(os.environ, env, clear=True):
            np_hook.register("SessionStart", "~/x/y.sh &", settings_path=self.settings)
        expected = "bash -lc '~/x/y.sh &'" if expect_wrap else "~/x/y.sh &"
        self.assertEqual(self._cmd_at(), expected)

    def test_malformed_settings_is_preserved_not_clobbered(self):
        # Fail-safe: a PRESENT-but-invalid settings.json must NOT be overwritten
        # (which would wipe the user's permissions/model). register() raises and
        # install_hooks() returns 1, both leaving the file byte-for-byte intact.
        bad = '{"permissions": {"allow": ["Bash"]}, oops not json'
        with open(self.settings, "w", encoding="utf-8") as fh:
            fh.write(bad)
        with self.assertRaises(ValueError):
            np_hook.register("SessionStart", "~/x/y.sh &", settings_path=self.settings)
        rc = np_hook.install_hooks(settings_path=self.settings)
        self.assertEqual(rc, 1)
        with open(self.settings, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), bad)


class TestPurge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.settings = os.path.join(self.tmp, "settings.json")
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_purge_drops_matching_substrings(self):
        seed = {"hooks": {"UserPromptSubmit": [
            {"matcher": "", "hooks": [{"type": "command", "command": "~/x/playbook-recall.sh"}]},
            {"matcher": "", "hooks": [{"type": "command", "command": "~/x/strategy-recall.sh"}]},
            {"matcher": "", "hooks": [{"type": "command", "command": "python3 .../cli.py hook lesson-recall"}]},
        ]}}
        with open(self.settings, "w") as fh:
            json.dump(seed, fh)
        np_hook.purge("UserPromptSubmit", ["playbook-recall.sh", "strategy-recall.sh", "lesson-recall.sh"],
                      settings_path=self.settings)
        s = _load(self.settings)
        # the .sh legacy entries gone; the cli.py dispatch (no .sh) survives
        self.assertEqual(_count(s, "UserPromptSubmit", "playbook-recall.sh"), 0)
        self.assertEqual(_count(s, "UserPromptSubmit", "strategy-recall.sh"), 0)
        self.assertEqual(_count(s, "UserPromptSubmit", "cli.py hook lesson-recall"), 1)

    def test_purge_scoped_to_matcher(self):
        seed = {"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/x/lesson-guard.sh"}]},
            {"matcher": "Read", "hooks": [{"type": "command", "command": "~/x/lesson-guard.sh"}]},
        ]}}
        with open(self.settings, "w") as fh:
            json.dump(seed, fh)
        np_hook.purge("PreToolUse", ["lesson-guard.sh"], matcher="Bash", settings_path=self.settings)
        s = _load(self.settings)
        self.assertEqual(len(s["hooks"]["PreToolUse"]), 1)
        self.assertEqual(s["hooks"]["PreToolUse"][0]["matcher"], "Read")


if __name__ == "__main__":
    unittest.main()
