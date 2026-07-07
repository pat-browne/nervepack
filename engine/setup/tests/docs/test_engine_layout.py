#!/usr/bin/env python3
"""Contract test for np-engine-layout-check.py (stdlib unittest, per language policy).

Covers the pure classifier, an end-to-end CLI run against a fixture repo (proves the
gate bites), and the live gate: the real engine tree must carry no overlay-only docs.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.abspath(os.path.join(HERE, "..", "..", "np-engine-layout-check.py"))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))  # engine root

_spec = importlib.util.spec_from_file_location("elc", CHK)
elc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(elc)


class TestScanPaths(unittest.TestCase):
    def test_flags_overlay_only_paths(self):
        bad = elc.scan_paths([
            "specs/x-design.md",
            "plans/y-implementation.md",
            "runbooks/z-runbook.md",
            "docs/superpowers/specs/a.md",
            "docs/superpowers/plans/b.md",
        ])
        self.assertEqual(sorted(bad), sorted([
            "specs/x-design.md", "plans/y-implementation.md",
            "runbooks/z-runbook.md", "docs/superpowers/specs/a.md",
            "docs/superpowers/plans/b.md",
        ]))

    def test_allows_engine_paths(self):
        # docs/ (non-superpowers), engine machinery, skills, and nested fixture
        # dirs named specs/ are all legitimate.
        self.assertEqual(elc.scan_paths([
            "docs/ARCHITECTURE.md",
            "docs/FEATURES.md",
            "engine/setup/np-doctor.sh",
            "skills/np-kb-x/SKILL.md",
            "engine/setup/tests/docs/test_engine_layout.py",
            "engine/setup/tests/fixtures/specs/nested.md",
        ]), [])


class TestCliBitesOnFixture(unittest.TestCase):
    def test_cli_exit1_and_names_offender(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "-C", d, "init", "-q"], check=True)
            os.makedirs(os.path.join(d, "specs"))
            open(os.path.join(d, "specs", "bad-design.md"), "w").close()
            subprocess.run(["git", "-C", d, "add", "specs/bad-design.md"], check=True)
            rc = subprocess.run([sys.executable, CHK, d],
                                capture_output=True, text=True)
            self.assertEqual(rc.returncode, 1, rc.stdout + rc.stderr)
            self.assertIn("bad-design.md", rc.stderr)

    def test_cli_clean_repo_passes(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "-C", d, "init", "-q"], check=True)
            os.makedirs(os.path.join(d, "engine", "setup"))
            open(os.path.join(d, "engine", "setup", "ok.sh"), "w").close()
            subprocess.run(["git", "-C", d, "add", "engine/setup/ok.sh"], check=True)
            rc = subprocess.run([sys.executable, CHK, d],
                                capture_output=True, text=True)
            self.assertEqual(rc.returncode, 0, rc.stderr)


class TestRealEngineTreeClean(unittest.TestCase):
    """The live gate: no overlay-only docs may be committed to this engine repo."""
    def test_engine_tree_has_no_overlay_docs(self):
        rc = subprocess.run([sys.executable, CHK, REPO],
                            capture_output=True, text=True)
        self.assertEqual(rc.returncode, 0, rc.stderr)


if __name__ == "__main__":
    unittest.main()
