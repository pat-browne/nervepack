import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.abspath(os.path.join(HERE, "..", ".."))  # engine/setup
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)

import np_skill_maintain  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _oversized_skill(root, name):
    """An over-8KB SKILL.md with a cross-link (the split candidate shape)."""
    _write(os.path.join(root, "skills", name, "SKILL.md"),
           "---\nname: %s\ndescription: a big skill\n---\n[[np-core-sync]]\n%s\n"
           % (name, "x" * 9000))


class BudgetAndGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "np")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "skills"))
        self.log = os.path.join(self.tmp, "log")
        # Point the module's _NP at our sandbox engine root, and toggles at a
        # sandbox toggles.conf so np_toggle reads our thresholds.
        _write(os.path.join(self.np, "engine", "setup", "toggles.conf"),
               "skills|shared|runtime|on|split_kb=8,soft_kb=6,catalog_tok=4000,"
               "max_per_run=2,graduate_seen=10,graduate_kb=6\n")
        self.env = mock.patch.dict(os.environ, {
            "SKILL_MAINTAIN_LOG": self.log,
            "NP_CONTENT_DIR": self.np,
            "NP_TOGGLES_CONF": os.path.join(self.np, "engine", "setup", "toggles.conf"),
        })
        self.env.start()
        self.np_patch = mock.patch.object(np_skill_maintain, "_NP", self.np)
        self.np_patch.start()

    def tearDown(self):
        self.np_patch.stop()
        self.env.stop()

    def test_toggle_off_skips_without_scanning(self):
        with mock.patch.object(np_skill_maintain.np_toggle, "enabled",
                               return_value=False):
            with mock.patch.object(np_skill_maintain.np_skill_budget, "scan") as scan:
                result = np_skill_maintain.maintain()
        self.assertEqual(result, "skipped: skills disabled")
        scan.assert_not_called()

    def test_skill_roots_include_engine_and_overlay(self):
        overlay = os.path.join(self.tmp, "overlay")
        os.makedirs(os.path.join(overlay, "skills"))
        with mock.patch.object(np_skill_maintain.np_content, "merge_roots",
                               return_value=[overlay, self.np]):
            roots = np_skill_maintain._skill_roots()
        self.assertEqual(roots[0], os.path.join(self.np, "skills"))
        self.assertIn(os.path.join(overlay, "skills"), roots)
        # The engine root itself is never double-added via merge_roots.
        self.assertEqual(roots.count(os.path.join(self.np, "skills")), 1)

    def test_no_candidates_is_noop(self):
        # A single small skill: under the split threshold -> no candidates.
        _write(os.path.join(self.np, "skills", "small", "SKILL.md"),
               "---\nname: small\ndescription: d\n---\nbody\n")
        result = np_skill_maintain.maintain()
        self.assertTrue(result.startswith("no-op"))
        with open(self.log, encoding="utf-8") as fh:
            self.assertIn("no skills over split threshold", fh.read())

    def test_catalog_over_budget_note(self):
        # Description must be long enough that catalog_tokens (desc_chars // 4)
        # is nonzero -- a 1-char description truncates to 0 tokens, which would
        # make "0 > 0" false regardless of how low the budget is forced.
        _write(os.path.join(self.np, "skills", "small", "SKILL.md"),
               "---\nname: small\ndescription: a small skill\n---\nbody\n")
        # Force catalog_over True via a tiny catalog token budget.
        with mock.patch.dict(os.environ, {"SKILL_CATALOG_TOK": "0"}):
            with mock.patch.object(np_skill_maintain.np_toggle, "param",
                                   side_effect=lambda k, d: "0" if k == "skills.catalog_tok" else d):
                np_skill_maintain.maintain()
        with open(self.log, encoding="utf-8") as fh:
            self.assertIn("catalog over budget", fh.read())

    def test_split_disabled_detects_only(self):
        _oversized_skill(self.np, "big")
        def _param(key, default):
            return default
        def _enabled(feature):
            return feature == "skills"  # skills on, skills.split off
        with mock.patch.object(np_skill_maintain.np_toggle, "param", side_effect=_param):
            with mock.patch.object(np_skill_maintain.np_toggle, "enabled", side_effect=_enabled):
                result = np_skill_maintain.maintain()
        self.assertIn("skills.split disabled", result)
        with open(self.log, encoding="utf-8") as fh:
            self.assertIn("skills.split disabled; detected: big", fh.read())


class ArchitectureFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "log")
        self.cache = os.path.join(self.tmp, ".cache", "nervepack")
        self.marker = os.path.join(self.cache, "architecture-stale")
        self.env = mock.patch.dict(os.environ, {
            "SKILL_MAINTAIN_LOG": self.log, "HOME": self.tmp})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _stub_freshness(self, body):
        """Point _HERE at a temp dir holding a stub np-architecture-freshness.sh."""
        stub_dir = os.path.join(self.tmp, "setup")
        os.makedirs(stub_dir, exist_ok=True)
        path = os.path.join(stub_dir, "np-architecture-freshness.sh")
        _write(path, "#!/usr/bin/env bash\n%s\n" % body)
        os.chmod(path, 0o755)
        return mock.patch.object(np_skill_maintain, "_HERE", stub_dir)

    def test_stale_writes_marker(self):
        with self._stub_freshness('echo "STALE: docs/foo.md not in map"'):
            np_skill_maintain._architecture_freshness()
        self.assertTrue(os.path.isfile(self.marker))
        with open(self.marker, encoding="utf-8") as fh:
            self.assertIn("STALE:", fh.read())

    def test_clean_removes_stale_marker(self):
        os.makedirs(self.cache, exist_ok=True)
        _write(self.marker, "old drift\n")
        with self._stub_freshness('echo "OK: map fresh"'):
            np_skill_maintain._architecture_freshness()
        self.assertFalse(os.path.exists(self.marker))


class GraduationScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.content = os.path.join(self.tmp, "content")
        os.makedirs(os.path.join(self.content, "memory", "lessons"))
        _write(os.path.join(self.content, "memory", "lessons", "proven.md"),
               "---\nname: proven\nkind: lesson\nprovenance: failure\n"
               "status: candidate\nseen: 20\n---\nbody\n")
        self.log = os.path.join(self.tmp, "log")
        self.grad = os.path.join(self.tmp, "grad")
        self.env = mock.patch.dict(os.environ, {
            "SKILL_MAINTAIN_LOG": self.log, "GRADUATION_MARKER": self.grad,
            "GRADUATE_SEEN": "10", "GRADUATE_KB": "6"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_explicit_content_surfaces_candidate(self):
        with mock.patch.object(np_skill_maintain.np_content, "content_is_explicit",
                               return_value=True), \
             mock.patch.object(np_skill_maintain.np_content, "content_dir",
                               return_value=self.content), \
             mock.patch.object(np_skill_maintain.np_toggle, "param",
                               side_effect=lambda k, d: d):
            np_skill_maintain._graduation_scan()
        with open(self.log, encoding="utf-8") as fh:
            self.assertIn("GRADUATE: failure proven", fh.read())
        self.assertTrue(os.path.isfile(self.grad))
        with open(self.grad, encoding="utf-8") as fh:
            self.assertIn('"name":"proven"', fh.read())
        data = os.path.join(self.content, "dashboard", "data", "graduation-candidates.json")
        self.assertTrue(os.path.isfile(data))
        with open(data, encoding="utf-8") as fh:
            self.assertIn('"name":"proven"', fh.read())

    def test_implicit_fallback_skips(self):
        with mock.patch.object(np_skill_maintain.np_content, "content_is_explicit",
                               return_value=False):
            np_skill_maintain._graduation_scan()
        data = os.path.join(self.content, "dashboard", "data", "graduation-candidates.json")
        self.assertFalse(os.path.exists(data))
        self.assertFalse(os.path.exists(self.grad))


if __name__ == "__main__":
    unittest.main()
