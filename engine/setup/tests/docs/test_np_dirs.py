#!/usr/bin/env python3
# np-test: np-dirs | happy
"""Tests for np_dirs -- where nervepack keeps per-machine state (F11/#299).

These directories hold a real OAuth token and the memory pipeline's queues, so
the failure that matters is not "wrong path" but "state silently somewhere
else". Every test below is written against that.
"""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_dirs  # noqa: E402


class _Env(object):
    """Isolated HOME and XDG_* for one case."""

    def __init__(self, home, **xdg):
        self.home, self.xdg, self.saved = home, xdg, {}

    def __enter__(self):
        for key in ("HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
            self.saved[key] = os.environ.get(key)
        os.environ["HOME"] = self.home
        for key in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
            value = self.xdg.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        np_dirs._legacy_wins.clear()
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        np_dirs._legacy_wins.clear()


class TestTheDefaultIsUnchanged(unittest.TestCase):
    """Nothing may move on an existing install, on any platform."""

    def test_unset_resolves_to_the_historical_paths(self):
        with tempfile.TemporaryDirectory() as home, _Env(home):
            self.assertEqual(np_dirs.cache_dir(),
                             os.path.join(home, ".cache", "nervepack"))
            self.assertEqual(np_dirs.config_dir(),
                             os.path.join(home, ".config", "nervepack"))

    def test_the_defaults_match_what_the_call_sites_used_to_build(self):
        """Byte-for-byte, because a one-character difference here relocates a
        credential."""
        with tempfile.TemporaryDirectory() as home, _Env(home):
            self.assertEqual(np_dirs.cache_path("episodic-inbox"),
                             os.path.join(home, ".cache", "nervepack",
                                          "episodic-inbox"))
            self.assertEqual(np_dirs.config_path("claude-oauth-token"),
                             os.path.join(home, ".config", "nervepack",
                                          "claude-oauth-token"))


class TestAnAbsoluteXdgValueIsHonoured(unittest.TestCase):
    def test_a_fresh_install_uses_it(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CACHE_HOME=xdg):
            self.assertEqual(np_dirs.cache_dir(),
                             os.path.join(xdg, "nervepack"))

    def test_config_and_cache_are_independent(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CONFIG_HOME=xdg):
            self.assertEqual(np_dirs.config_dir(), os.path.join(xdg, "nervepack"))
            self.assertEqual(np_dirs.cache_dir(),
                             os.path.join(home, ".cache", "nervepack"))


class TestARelativeXdgValueRaises(unittest.TestCase):
    """The XDG spec calls a relative value invalid. Normalising it would anchor
    state to whatever directory a hook happened to start in."""

    def test_it_raises_rather_than_normalising(self):
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CACHE_HOME="relative/path"):
            with self.assertRaises(np_dirs.DirectoryError):
                np_dirs.cache_dir()

    def test_the_message_says_why(self):
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CONFIG_HOME="also/relative"):
            try:
                np_dirs.config_dir()
            except np_dirs.DirectoryError as exc:
                self.assertIn("relative", str(exc))
                self.assertIn("XDG_CONFIG_HOME", str(exc))
            else:
                self.fail("a relative XDG_CONFIG_HOME was accepted")

    def test_a_dot_prefixed_value_is_still_relative(self):
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CACHE_HOME="./cache"):
            with self.assertRaises(np_dirs.DirectoryError):
                np_dirs.cache_dir()


class TestLegacyPrecedence(unittest.TestCase):
    """git's rule: ~/.gitconfig beats $XDG_CONFIG_HOME/git/config.

    Without it, exporting XDG_CACHE_HOME for an unrelated program silently
    orphans the episodic inbox, the toggles and the OAuth token.
    """

    def test_legacy_wins_when_it_exists_and_the_derived_does_not(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CACHE_HOME=xdg):
            legacy = os.path.join(home, ".cache", "nervepack")
            os.makedirs(legacy)
            self.assertEqual(np_dirs.cache_dir(), legacy)

    def test_the_derived_wins_once_it_exists(self):
        """A machine that already moved is not dragged back."""
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CACHE_HOME=xdg):
            os.makedirs(os.path.join(home, ".cache", "nervepack"))
            derived = os.path.join(xdg, "nervepack")
            os.makedirs(derived)
            self.assertEqual(np_dirs.cache_dir(), derived)

    def test_a_fresh_machine_with_no_legacy_uses_the_derived(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CACHE_HOME=xdg):
            self.assertEqual(np_dirs.cache_dir(), os.path.join(xdg, "nervepack"))

    def test_it_is_reported_so_the_doctor_can_explain_it(self):
        """'My XDG_CACHE_HOME is being ignored' must be answerable without
        reading source."""
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CACHE_HOME=xdg):
            os.makedirs(os.path.join(home, ".cache", "nervepack"))
            np_dirs.cache_dir()
            self.assertEqual(np_dirs.legacy_overrides(), ["XDG_CACHE_HOME"])

    def test_nothing_is_reported_when_no_override_happened(self):
        with tempfile.TemporaryDirectory() as home, _Env(home):
            np_dirs.cache_dir()
            self.assertEqual(np_dirs.legacy_overrides(), [])


class TestTheResolverCreatesNothing(unittest.TestCase):
    """A resolver with a side effect cannot be asked a question. It also must
    not create a directory as root from a cron, or under a path the user set by
    mistake."""

    def test_asking_does_not_make_the_directory(self):
        with tempfile.TemporaryDirectory() as home, _Env(home):
            path = np_dirs.cache_dir()
            self.assertFalse(os.path.exists(path))

    def test_asking_does_not_make_the_xdg_directory_either(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CONFIG_HOME=xdg):
            path = np_dirs.config_dir()
            self.assertFalse(os.path.exists(path))



class TestTheConfigSitesAreConverted(unittest.TestCase):
    """The 8 config sites now go through np_dirs. This keeps them from regrowing
    inline, which is how there came to be 51 of them."""

    REPO = os.path.normpath(os.path.join(_ENGINE_SETUP, "..", ".."))
    INLINE = re.compile(r'"\.config"\s*,\s*"nervepack"|expanduser\("~/\.config/nervepack')

    def _sources(self):
        for dirpath, dirnames, files in os.walk(os.path.join(self.REPO, "engine")):
            if "tests" in dirpath.split(os.sep):
                continue
            for name in sorted(files):
                if name.endswith(".py") and name != "np_dirs.py":
                    yield os.path.join(dirpath, name)

    def test_no_module_builds_the_config_dir_inline(self):
        offenders = []
        for path in self._sources():
            with open(path, encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    if line.strip().startswith("#"):
                        continue
                    if self.INLINE.search(line):
                        rel = os.path.relpath(path, self.REPO)
                        offenders.append("%s:%d" % (rel, number))
        self.assertEqual(offenders, [],
                         "use np_dirs.config_path(...) instead:\n  "
                         + "\n  ".join(offenders))

    def test_vs_codes_own_config_path_is_untouched(self):
        """The single most likely casualty of a pattern-based sweep here:
        np_bootstrap builds ~/.config/Code/User/settings.json, which belongs to
        VS Code and must NOT be routed through nervepack's resolver."""
        path = os.path.join(self.REPO, "engine", "setup", "np_bootstrap.py")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('".config", "Code", "User", "settings.json"', text)
        self.assertNotIn("np_dirs.config_path(\"Code\"", text)

    def test_the_sync_status_file_is_left_outside_the_app_dir(self):
        """~/.cache/np-core-sync-status sits directly under .cache, not under
        nervepack/. Routing it through cache_path() would MOVE it, and the
        np-core-sync skill documents the path. Left alone deliberately."""
        path = os.path.join(self.REPO, "engine", "nervepack_engine", "np_sync.py")
        with open(path, encoding="utf-8") as fh:
            self.assertIn('".cache", "np-core-sync-status"', fh.read())



class TestTheDoctorActuallyReportsIt(unittest.TestCase):
    """The spec and docs/XDG-DIRECTORIES.md both promise the doctor surfaces
    legacy precedence. A promise with no call site is the same defect as an
    unreachable branch: it advertises an intent the code does not implement."""

    def test_the_toggles_check_names_the_ignored_variable(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(_ENGINE_SETUP), "nervepack_engine"))
        import np_doctor
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CACHE_HOME=os.path.join(home, "elsewhere")):
            os.makedirs(os.path.join(home, ".cache", "nervepack"))
            result = np_doctor._core_check("toggles", _ENGINE_SETUP)
        self.assertIn("XDG_CACHE_HOME", result)
        self.assertTrue(result.startswith("PASS"), result)

    def test_it_says_plain_pass_when_nothing_is_ignored(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(_ENGINE_SETUP), "nervepack_engine"))
        import np_doctor
        with tempfile.TemporaryDirectory() as home, _Env(home):
            self.assertEqual(np_doctor._core_check("toggles", _ENGINE_SETUP), "PASS")


if __name__ == "__main__":
    unittest.main()
