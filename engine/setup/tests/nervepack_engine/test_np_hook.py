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



class TestTheInstallPathIsNotAssumed(unittest.TestCase):
    """#257/F11. Every manifest row used to carry ~/Code/nervepack literally, so
    a clone anywhere else registered 26 hooks pointing at a directory that does
    not exist -- and hooks fail open, so nothing would have errored. The whole
    system would simply have done nothing."""

    MANIFEST = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "hooks.manifest")

    def test_no_manifest_row_hardcodes_an_install_path(self):
        """Comment lines are excluded: the header explains what was removed and
        why, and a check that cannot tell the explanation from the thing it
        warns about would push the explanation out of the file."""
        with open(self.MANIFEST, encoding="utf-8") as fh:
            rows = [ln for ln in fh.read().splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
        self.assertTrue(rows, "no manifest rows found - has the file moved?")
        for row in rows:
            self.assertNotIn("Code/nervepack", row, row)

    def test_every_row_that_names_the_engine_uses_the_token(self):
        with open(self.MANIFEST, encoding="utf-8") as fh:
            rows = [ln for ln in fh.read().splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
        engine_rows = [r for r in rows if "cli.py" in r]
        self.assertTrue(engine_rows)
        for row in engine_rows:
            self.assertIn(np_hook.NP_DIR_TOKEN, row, row)

    def test_the_token_is_substituted_with_the_given_root(self):
        rows = np_hook.read_manifest(self.MANIFEST, root="/opt/nervepack")
        self.assertTrue(rows)
        for _, _, command in rows:
            self.assertNotIn(np_hook.NP_DIR_TOKEN, command)
        self.assertIn("/opt/nervepack/engine", rows[0][2])

    def test_a_windows_root_is_normalised_to_forward_slashes(self):
        """These commands are routed through bash on a Git-bash host, where a
        backslash is an escape character rather than a separator."""
        rows = np_hook.read_manifest(self.MANIFEST, root="D:\\src\\nervepack")
        self.assertIn("D:/src/nervepack/engine", rows[0][2])
        self.assertNotIn("\\", rows[0][2])

    def test_no_row_still_contains_the_token_after_a_default_read(self):
        for _, _, command in np_hook.read_manifest(self.MANIFEST):
            self.assertNotIn(np_hook.NP_DIR_TOKEN, command)


class TestRegisteringFromAWorktreeUsesTheMainCheckout(unittest.TestCase):
    """Registering from `.worktrees/feat-x` would write 26 hook commands pointing
    INTO that worktree, and the next `git worktree remove` would leave every hook
    on the machine pointing at a deleted directory -- silently, because hooks
    fail open."""

    def test_a_linked_worktree_resolves_to_its_main_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            main = os.path.join(d, "main")
            os.makedirs(os.path.join(main, ".git", "worktrees", "feat-x"))
            wt = os.path.join(d, "main", ".worktrees", "feat-x")
            os.makedirs(wt)
            with open(os.path.join(wt, ".git"), "w") as f:
                f.write("gitdir: %s\n" % os.path.join(main, ".git", "worktrees", "feat-x"))
            self.assertEqual(np_hook.main_worktree_root(wt), main)

    def test_a_normal_checkout_is_returned_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".git"))
            self.assertEqual(np_hook.main_worktree_root(d), d)

    def test_something_that_is_not_a_checkout_is_returned_unchanged(self):
        """Best-effort correction, never a precondition."""
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(np_hook.main_worktree_root(d), d)

    def test_a_dot_git_file_that_is_not_a_gitdir_pointer_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".git"), "w") as f:
                f.write("something else\n")
            self.assertEqual(np_hook.main_worktree_root(d), d)



class TestTheResolvedRootIsValidated(unittest.TestCase):
    """These commands are interpolated into a bash word UNQUOTED, so anything
    the shell would act on has to be rejected rather than substituted.

    Quoting the path instead would break `_CLI_TAIL`, which keys the dedup on
    `cli.py` followed by whitespace - every hook would then re-register under a
    different key on the next sync."""

    MANIFEST = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "hooks.manifest")

    def test_a_command_substitution_is_rejected(self):
        with self.assertRaises(np_hook.UnsafeRootError):
            np_hook.read_manifest(self.MANIFEST, root="/tmp/$(id)/nervepack")

    def test_a_backtick_is_rejected(self):
        with self.assertRaises(np_hook.UnsafeRootError):
            np_hook.read_manifest(self.MANIFEST, root="/tmp/`id`/nervepack")

    def test_whitespace_is_rejected(self):
        """More likely than an injection in practice: an unquoted path with a
        space splits into two argv tokens."""
        with self.assertRaises(np_hook.UnsafeRootError):
            np_hook.read_manifest(self.MANIFEST, root="/home/my user/nervepack")

    def test_a_relative_root_is_rejected(self):
        """It would resolve against whatever directory the session started in."""
        with self.assertRaises(np_hook.UnsafeRootError):
            np_hook.read_manifest(self.MANIFEST, root="relative/nervepack")

    def test_the_message_names_the_offending_character(self):
        try:
            np_hook.read_manifest(self.MANIFEST, root="/tmp/a;b/nervepack")
        except np_hook.UnsafeRootError as exc:
            self.assertIn(";", str(exc))
        else:
            self.fail("a semicolon in the root was accepted")

    def test_an_ordinary_absolute_root_is_accepted(self):
        """This is the Windows-lane regression test.

        The first version of this check used os.path.isabs, which on Python 3.13
        and later rejects "/opt/x" for having no drive letter. The same root
        therefore validated on Linux and failed on the Windows lane - a
        platform-dependent assumption inside the change that exists to remove
        platform-dependent assumptions. Absoluteness is now judged from the
        string alone, identically everywhere."""
        rows = np_hook.read_manifest(self.MANIFEST, root="/opt/nervepack")
        self.assertIn("/opt/nervepack/engine", rows[0][2])

    def test_absoluteness_never_consults_the_local_platform(self):
        """The judgement is about a string that will run on the TARGET machine."""
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "..", "..", "nervepack_engine", "np_hook.py"),
                  encoding="utf-8") as fh:
            source = fh.read()
        head = source.split("def _repo_root_for_commands", 1)[1].split("def ", 1)[0]
        self.assertNotIn("os.path.isabs", head)

    def test_a_windows_drive_root_is_accepted(self):
        rows = np_hook.read_manifest(self.MANIFEST, root="D:\\src\\nervepack")
        self.assertIn("D:/src/nervepack/engine", rows[0][2])

    def test_an_empty_root_falls_back_to_the_real_one(self):
        """`root or np_paths.REPO_ROOT` - the documented default, not a hole."""
        rows = np_hook.read_manifest(self.MANIFEST, root="")
        self.assertIn("/engine/nervepack_engine/cli.py", rows[0][2])
        self.assertNotIn(np_hook.NP_DIR_TOKEN, rows[0][2])


if __name__ == "__main__":
    unittest.main()
