#!/usr/bin/env python3
# np-test: np-host | happy
"""Tests for np_host -- where the HOST keeps things (F11/#300).

Distinct from np_dirs, which answers where NERVEPACK keeps its own state. The
failure that matters here is a settings file resolved to the wrong place: the
hook registrar WRITES to it, so a wrong answer either edits someone else's file
or registers hooks nowhere.
"""
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(HERE, "..", ".."))
if _ENGINE_SETUP not in sys.path:
    sys.path.insert(0, _ENGINE_SETUP)

import np_host  # noqa: E402

REPO = os.path.normpath(os.path.join(_ENGINE_SETUP, "..", ".."))
KEYS = ("settings", "skills_dir", "transcripts")


class _Env(object):
    """Isolated HOME, adapter and every host env override."""

    VARS = ("HOME", "NP_ADAPTER", "CLAUDE_SETTINGS", "NP_SKILLS_DST",
            "CLAUDE_PROJECTS_DIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")

    def __init__(self, home, **over):
        self.home, self.over, self.saved = home, over, {}

    def __enter__(self):
        for key in self.VARS:
            self.saved[key] = os.environ.get(key)
            os.environ.pop(key, None)
        os.environ["HOME"] = self.home
        os.environ.update(self.over)
        np_host._invalid.clear()
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        np_host._invalid.clear()


def _adapter(tmp, paths):
    path = os.path.join(tmp, "adapter.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"host": "test", "paths": paths}, fh)
    return path


class TestTheDefaultIsUnchanged(unittest.TestCase):
    """Nothing moves on a machine with no `paths` block, which is every machine
    today."""

    def test_all_three_resolve_under_dot_claude(self):
        with tempfile.TemporaryDirectory() as home, _Env(home):
            self.assertEqual(np_host.settings_path(),
                             os.path.join(home, ".claude", "settings.json"))
            self.assertEqual(np_host.skills_dir(),
                             os.path.join(home, ".claude", "skills"))
            self.assertEqual(np_host.transcripts_dir(),
                             os.path.join(home, ".claude", "projects"))

    def test_an_adapter_without_a_paths_block_changes_nothing(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "adapter.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"host": "test", "capabilities": {}}, fh)
            with _Env(home, NP_ADAPTER=path):
                self.assertEqual(np_host.settings_path(),
                                 os.path.join(home, ".claude", "settings.json"))


class TestPrecedence(unittest.TestCase):
    """env -> adapter -> default. The environment keeps winning because it
    already did: capabilities.json tells a non-Claude host to set
    CLAUDE_SETTINGS, and a manifest that could not be overridden would be worse
    than no manifest."""

    def test_the_environment_beats_the_adapter(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"settings": "/from/adapter.json"})
            with _Env(home, NP_ADAPTER=a, CLAUDE_SETTINGS="/from/env.json"):
                self.assertEqual(np_host.settings_path(), "/from/env.json")

    def test_the_adapter_beats_the_default(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"settings": "/from/adapter.json"})
            with _Env(home, NP_ADAPTER=a):
                self.assertEqual(np_host.settings_path(), "/from/adapter.json")

    def test_each_key_has_its_own_env_var(self):
        with tempfile.TemporaryDirectory() as home:
            with _Env(home, NP_SKILLS_DST="/s", CLAUDE_PROJECTS_DIR="/p"):
                self.assertEqual(np_host.skills_dir(), "/s")
                self.assertEqual(np_host.transcripts_dir(), "/p")
                self.assertEqual(np_host.settings_path(),
                                 os.path.join(home, ".claude", "settings.json"))


class TestThePathsBlockIsOptionalPerKey(unittest.TestCase):
    """Every manifest on disk today has no `paths` at all, so a partial one must
    behave exactly as today for whatever it omits."""

    def test_an_omitted_key_falls_back(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"settings": "/only/settings.json"})
            with _Env(home, NP_ADAPTER=a):
                self.assertEqual(np_host.settings_path(), "/only/settings.json")
                self.assertEqual(np_host.skills_dir(),
                                 os.path.join(home, ".claude", "skills"))

    def test_an_empty_value_falls_back(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"settings": "   "})
            with _Env(home, NP_ADAPTER=a):
                self.assertEqual(np_host.settings_path(),
                                 os.path.join(home, ".claude", "settings.json"))

    def test_a_non_string_value_falls_back(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"settings": {"nested": "oops"}})
            with _Env(home, NP_ADAPTER=a):
                self.assertEqual(np_host.settings_path(),
                                 os.path.join(home, ".claude", "settings.json"))


class TestAManifestIsHandWrittenSoTildeExpands(unittest.TestCase):
    def test_a_tilde_is_expanded(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"skills_dir": "~/elsewhere/skills"})
            with _Env(home, NP_ADAPTER=a):
                self.assertEqual(np_host.skills_dir(),
                                 os.path.join(home, "elsewhere", "skills"))


class TestARelativeValueIsIgnoredAndReported(unittest.TestCase):
    """Same rule as np_dirs, for the same reason: these resolve inside hooks
    that start in whatever directory the user opened."""

    def test_it_falls_back(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"settings": "relative/settings.json"})
            with _Env(home, NP_ADAPTER=a):
                self.assertEqual(np_host.settings_path(),
                                 os.path.join(home, ".claude", "settings.json"))

    def test_it_does_not_raise(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"transcripts": "./projects"})
            with _Env(home, NP_ADAPTER=a):
                np_host.transcripts_dir()

    def test_it_is_reported(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            a = _adapter(t, {"settings": "relative/settings.json"})
            with _Env(home, NP_ADAPTER=a):
                np_host.settings_path()
                self.assertEqual(np_host.invalid_values(),
                                 {"settings": "relative/settings.json"})


class TestABrokenAdapterNeverBreaksResolution(unittest.TestCase):
    """np_hook and the recall hooks resolve through here, and hooks fail open.
    A malformed manifest must degrade to the defaults, not take the lifecycle
    down -- the doctor reports a broken adapter through its own check."""

    def test_unparseable_json_falls_back(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "adapter.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            with _Env(home, NP_ADAPTER=path):
                self.assertEqual(np_host.settings_path(),
                                 os.path.join(home, ".claude", "settings.json"))

    def test_a_missing_adapter_falls_back(self):
        with tempfile.TemporaryDirectory() as home:
            with _Env(home, NP_ADAPTER="/nonexistent/adapter.json"):
                self.assertEqual(np_host.skills_dir(),
                                 os.path.join(home, ".claude", "skills"))

    def test_a_paths_block_that_is_not_an_object_falls_back(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "adapter.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"host": "x", "paths": ["oops"]}, fh)
            with _Env(home, NP_ADAPTER=path):
                self.assertEqual(np_host.settings_path(),
                                 os.path.join(home, ".claude", "settings.json"))


class TestTheResolverCreatesNothing(unittest.TestCase):
    def test_asking_makes_no_directory(self):
        with tempfile.TemporaryDirectory() as home, _Env(home):
            for path in (np_host.settings_path(), np_host.skills_dir(),
                         np_host.transcripts_dir()):
                self.assertFalse(os.path.exists(path), path)


class TestTheCoreNoLongerNamesTheHost(unittest.TestCase):
    """The point of a port: the tool-neutral core does not know the host's name.
    The hooks and np_hook DO -- they parse its payloads and write its settings
    file. That is what an adapter is."""

    ADAPTER_LAYER = ("nervepack_engine/hooks/", "nervepack_engine/np_hook.py",
                     "setup/np_host.py")
    # The host's env vars anywhere, and `.claude` only where a PATH is being
    # BUILT. np_layout lists ".claude" in a frozenset of directory names not to
    # descend into, beside ".git" and "node_modules" -- that is membership, not
    # resolution, and flagging it would push a correct skip-list into an
    # exemption list.
    ENV_NAMES = re.compile(r'CLAUDE_SETTINGS|CLAUDE_PROJECTS_DIR|NP_SKILLS_DST')
    BUILDS_PATH = re.compile(r'\.claude')
    JOINING = re.compile(r'join\(|expanduser\(')

    @staticmethod
    def _prose_lines(source):
        """Line numbers covered by a DOCSTRING.

        Docstrings only, not every string literal. An earlier version collected
        all of them, which silently disabled this whole check: every offending
        line contains the literal "CLAUDE_SETTINGS", so marking string-bearing
        lines as prose made the guard pass on a planted violation. Caught by
        planting one -- which is the only way to tell a passing guard from a
        vacuous one.
        """
        import ast
        covered = set()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return covered
        holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        for node in ast.walk(tree):
            if not isinstance(node, holders):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                end = getattr(first, "end_lineno", first.lineno) or first.lineno
                covered.update(range(first.lineno, end + 1))
        return covered

    def test_no_tool_neutral_module_names_it_in_code(self):
        offenders = []
        for dirpath, dirnames, files in os.walk(os.path.join(REPO, "engine")):
            if "tests" in dirpath.split(os.sep):
                continue
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, os.path.join(REPO, "engine"))
                rel = rel.replace(os.sep, "/")
                if any(rel.startswith(a) or rel == a for a in self.ADAPTER_LAYER):
                    continue
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
                prose = self._prose_lines(source)
                for number, line in enumerate(source.split("\n"), 1):
                    stripped = line.strip()
                    if stripped.startswith("#") or number in prose:
                        continue
                    hit = (self.ENV_NAMES.search(line)
                           or (self.BUILDS_PATH.search(line)
                               and self.JOINING.search(line)))
                    if hit:
                        offenders.append("%s:%d %s" % (rel, number, stripped[:70]))
        self.assertEqual(offenders, [],
                         "route these through np_host:\n  " + "\n  ".join(offenders))

    def test_a_skip_list_naming_the_directory_is_not_flagged(self):
        """`.claude` in a set of directory names not to walk into is membership,
        not resolution. Flagging it would push a correct skip-list into an
        exemption list, which is how a guard starts accumulating excuses."""
        self.assertIsNone(self.ENV_NAMES.search('    ".git", ".claude", "node_modules"))'))
        line = '    ".git", ".claude", "node_modules"))'
        self.assertIsNone(self.JOINING.search(line))

    def test_a_path_being_built_is_flagged(self):
        line = '    return os.path.join(home, ".claude", "settings.json")'
        self.assertTrue(self.BUILDS_PATH.search(line) and self.JOINING.search(line))

    def test_the_adapter_layer_is_narrow(self):
        """If this list grows, the port has leaked rather than moved."""
        self.assertEqual(len(self.ADAPTER_LAYER), 3)


if __name__ == "__main__":
    unittest.main()
