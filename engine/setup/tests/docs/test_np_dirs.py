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
        np_dirs._invalid.clear()
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        np_dirs._legacy_wins.clear()
        np_dirs._invalid.clear()


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


class TestARelativeXdgValueIsIgnoredAndReported(unittest.TestCase):
    """The XDG spec says a relative value "should be considered invalid and
    ignored". An earlier draft raised, following Go's stdlib. That was wrong
    here: np_toggle resolves through np_dirs, sixteen hook modules read toggles,
    and hooks fail open -- so raising would have let one bad environment variable
    silently disable the whole session lifecycle."""

    def test_it_falls_back_to_the_default(self):
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CACHE_HOME="relative/path"):
            self.assertEqual(np_dirs.cache_dir(),
                             os.path.join(home, ".cache", "nervepack"))

    def test_it_does_not_raise(self):
        """The whole point. A raise here reaches sixteen fail-open hooks."""
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CONFIG_HOME="also/relative"):
            np_dirs.config_dir()

    def test_it_is_reported_with_the_offending_value(self):
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CONFIG_HOME="also/relative"):
            np_dirs.config_dir()
            self.assertEqual(np_dirs.invalid_values(),
                             {"XDG_CONFIG_HOME": "also/relative"})

    def test_a_dot_prefixed_value_is_still_relative(self):
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CACHE_HOME="./cache"):
            self.assertEqual(np_dirs.cache_dir(),
                             os.path.join(home, ".cache", "nervepack"))
            self.assertIn("XDG_CACHE_HOME", np_dirs.invalid_values())

    def test_fixing_the_value_clears_the_report(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as good, \
                _Env(home, XDG_CACHE_HOME="relative/path"):
            np_dirs.cache_dir()
            os.environ["XDG_CACHE_HOME"] = good
            np_dirs.cache_dir()
            self.assertEqual(np_dirs.invalid_values(), {})


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



class TestEverySiteIsConverted(unittest.TestCase):
    """No module builds either state directory inline any more.

    Stated as an invariant rather than a count on purpose: a number in a
    docstring is a snapshot that rots, and the assertion below is what actually
    holds the line. Two paths are deliberately outside it and each has its own
    test: VS Code's `~/.config/Code/User/settings.json`, which is not
    nervepack's, and `~/.cache/np-core-sync-status`, which lives outside the app
    directory and whose path a skill documents.
    """

    REPO = os.path.normpath(os.path.join(_ENGINE_SETUP, "..", ".."))
    INLINE = re.compile(
        r'"\.(?:config|cache)"\s*,\s*"nervepack"'
        r'|expanduser\("~/\.(?:config|cache)/nervepack')

    def _sources(self):
        for dirpath, dirnames, files in os.walk(os.path.join(self.REPO, "engine")):
            if "tests" in dirpath.split(os.sep):
                continue
            for name in sorted(files):
                if name.endswith(".py") and name != "np_dirs.py":
                    yield os.path.join(dirpath, name)

    def test_no_module_builds_either_dir_inline(self):
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



class TestTheMarkerReflectsOnlyTheCurrentEnvironment(unittest.TestCase):
    """A long-lived process -- the dashboard server, the MCP server -- resolves
    more than once. A stale entry would report a variable that is no longer set
    at all."""

    def test_unsetting_clears_the_INVALID_marker_too(self):
        """Both markers, not one. Clearing only `_legacy_wins` on the unset path
        is a bug this module shipped twice: once in `_legacy_wins` itself, and
        again in `_invalid` the moment it was added."""
        with tempfile.TemporaryDirectory() as home:
            with _Env(home, XDG_CONFIG_HOME="relative/oops"):
                np_dirs.config_dir()
                self.assertIn("XDG_CONFIG_HOME", np_dirs.invalid_values())
                os.environ.pop("XDG_CONFIG_HOME")
                np_dirs.config_dir()
                self.assertEqual(np_dirs.invalid_values(), {})

    def test_unsetting_the_variable_clears_the_marker(self):
        with tempfile.TemporaryDirectory() as home:
            with _Env(home, XDG_CACHE_HOME=os.path.join(home, "elsewhere")):
                os.makedirs(os.path.join(home, ".cache", "nervepack"))
                np_dirs.cache_dir()
                self.assertEqual(np_dirs.legacy_overrides(), ["XDG_CACHE_HOME"])
                os.environ.pop("XDG_CACHE_HOME")
                np_dirs.cache_dir()
                self.assertEqual(np_dirs.legacy_overrides(), [])


class TestTheDoctorSurvivesTheMisconfigurationItReports(unittest.TestCase):
    """A relative XDG_* value raises by design. The doctor calling the resolver
    must not die on precisely the misconfiguration it exists to diagnose."""

    def _doctor(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(_ENGINE_SETUP), "nervepack_engine"))
        import np_doctor
        return np_doctor

    def test_a_relative_value_reports_fail_and_names_the_value(self):
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CACHE_HOME="relative/oops"):
            result = self._doctor()._core_check("toggles", _ENGINE_SETUP)
        self.assertTrue(result.startswith("FAIL"), result)
        self.assertIn("relative/oops", result)

    def test_a_relative_config_value_is_caught_too(self):
        with tempfile.TemporaryDirectory() as home, \
                _Env(home, XDG_CONFIG_HOME="also/relative"):
            result = self._doctor()._core_check("toggles", _ENGINE_SETUP)
        self.assertTrue(result.startswith("FAIL"), result)



class TestTheDoctorSaysWhereStateActuallyLives(unittest.TestCase):
    """"Where is my credential" is what someone runs the doctor to find out.
    Named only when it is NOT the historical default, because printing it
    unconditionally buries the interesting case in noise on every machine."""

    def _doctor(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(_ENGINE_SETUP), "nervepack_engine"))
        import np_doctor
        return np_doctor

    def test_a_default_machine_says_only_pass(self):
        with tempfile.TemporaryDirectory() as home, _Env(home):
            self.assertEqual(
                self._doctor()._core_check("toggles", _ENGINE_SETUP), "PASS")

    def test_a_relocated_config_is_named(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CONFIG_HOME=xdg):
            result = self._doctor()._core_check("toggles", _ENGINE_SETUP)
        self.assertIn("config=", result)
        self.assertIn(xdg, result)

    def test_a_relocated_cache_is_named(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as xdg, \
                _Env(home, XDG_CACHE_HOME=xdg):
            result = self._doctor()._core_check("toggles", _ENGINE_SETUP)
        self.assertIn("cache=", result)


class TestANewBranchCannotLeaveAStaleMarker(unittest.TestCase):
    """Both markers are cleared once at the top of _resolve, before any branch
    decides anything, so a future branch that forgets to clear cannot reintroduce
    the staleness this module shipped twice."""

    def test_resolve_clears_before_it_branches(self):
        with open(os.path.join(_ENGINE_SETUP, "np_dirs.py"), encoding="utf-8") as fh:
            body = fh.read().split("def _resolve", 1)[1].split("def cache_dir", 1)[0]
        clear_at = body.index("_invalid.pop(env_var, None)")
        first_branch = body.index("if not base:")
        self.assertLess(clear_at, first_branch,
                        "markers must be cleared before the first branch")

    def test_no_branch_clears_a_marker_itself(self):
        """Each branch may only ADD. A discard inside one is the shape of the bug."""
        with open(os.path.join(_ENGINE_SETUP, "np_dirs.py"), encoding="utf-8") as fh:
            body = fh.read().split("def _resolve", 1)[1].split("def cache_dir", 1)[0]
        after = body[body.index("if not base:"):]
        self.assertNotIn("discard", after)
        self.assertNotIn(".pop(", after)


if __name__ == "__main__":
    unittest.main()
