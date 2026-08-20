#!/usr/bin/env python3
"""Contract test for np-spec-guard.py (stdlib unittest, per language policy).

Covers the pure helpers (branch slug, exemption heuristic, spec validation,
blast-radius matching) and the CLI end-to-end against a fixture repo — F2 in
the AI-native compliance epic (#248).
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.abspath(os.path.join(HERE, "..", "..", "np-spec-guard.py"))

_spec = importlib.util.spec_from_file_location("spec_guard", CHK)
spec_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spec_guard)

sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
import np_risk_tiers  # noqa: E402


class TestBranchSlug(unittest.TestCase):
    def test_replaces_slashes_with_dashes(self):
        self.assertEqual(spec_guard.branch_slug("feat/f2-thing"), "feat-f2-thing")

    def test_no_slash_unchanged(self):
        self.assertEqual(spec_guard.branch_slug("main"), "main")


class TestIsExempt(unittest.TestCase):
    def test_doc_only_diff_is_exempt(self):
        self.assertTrue(spec_guard.is_exempt(".", ["README.md", "docs/ARCHITECTURE.md"]))

    def test_test_only_diff_is_exempt(self):
        self.assertTrue(spec_guard.is_exempt(".", ["engine/setup/tests/docs/test_x.py"]))

    def test_code_change_is_not_exempt(self):
        self.assertFalse(spec_guard.is_exempt(".", ["engine/setup/np_toggle.py"]))

    def test_mixed_diff_is_not_exempt(self):
        self.assertFalse(spec_guard.is_exempt(".", ["README.md", "engine/setup/np_toggle.py"]))


class TestValidateSpec(unittest.TestCase):
    VALID = (
        "---\n"
        "id: 0001\n"
        "status: accepted\n"
        "date: 2026-08-14\n"
        "tier: normal\n"
        "blast_radius:\n"
        "  - engine/setup/**\n"
        "---\n"
        "# Title\nbody\n"
    )

    def test_valid_spec_has_no_problems(self):
        self.assertEqual(spec_guard.validate_spec(self.VALID), [])

    def test_missing_required_field_is_flagged(self):
        doc = self.VALID.replace("tier: normal\n", "")
        problems = spec_guard.validate_spec(doc)
        self.assertTrue(any("tier" in p for p in problems))

    def test_empty_blast_radius_is_flagged(self):
        doc = self.VALID.replace("blast_radius:\n  - engine/setup/**\n", "blast_radius:\n")
        problems = spec_guard.validate_spec(doc)
        self.assertTrue(any("blast_radius" in p for p in problems))

    def test_invalid_tier_is_flagged(self):
        doc = self.VALID.replace("tier: normal", "tier: bogus")
        problems = spec_guard.validate_spec(doc)
        self.assertTrue(any("tier" in p and "bogus" in p for p in problems))

    def test_needs_clarification_marker_is_flagged(self):
        doc = self.VALID + "\nSome [NEEDS CLARIFICATION] point.\n"
        problems = spec_guard.validate_spec(doc)
        self.assertTrue(any("NEEDS CLARIFICATION" in p for p in problems))

    def test_backtick_quoted_mention_is_not_flagged(self):
        # A spec describing the convention itself (e.g. "the `[NEEDS
        # CLARIFICATION]` marker") is talking about the marker, not leaving
        # one open - must not be flagged. Real bug, caught dogfooding this
        # tool on its own PR's spec (#248).
        doc = self.VALID + "\nUses the `[NEEDS CLARIFICATION]` marker.\n"
        problems = spec_guard.validate_spec(doc)
        self.assertFalse(any("NEEDS CLARIFICATION" in p for p in problems))


class TestDiffOutsideBlastRadius(unittest.TestCase):
    def test_all_covered_returns_empty(self):
        files = ["engine/setup/a.py", "engine/setup/b.py"]
        self.assertEqual(
            spec_guard.diff_outside_blast_radius(files, ["engine/setup/*"]), [])

    def test_uncovered_file_is_returned(self):
        files = ["engine/setup/a.py", "dashboard/build.py"]
        self.assertEqual(
            spec_guard.diff_outside_blast_radius(files, ["engine/setup/*"]),
            ["dashboard/build.py"])

    def test_no_globs_means_everything_is_outside(self):
        self.assertEqual(
            spec_guard.diff_outside_blast_radius(["a.py"], []), ["a.py"])


def _git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True)


def _write(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _init_repo(d):
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@example.com")
    _git(d, "config", "user.name", "t")
    _write(os.path.join(d, "README.md"), "base\n")
    _git(d, "add", "README.md")
    _git(d, "commit", "-q", "-m", "base")
    base_sha = subprocess.run(
        ["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return base_sha


def _head_sha(d):
    return subprocess.run(
        ["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


class TestCliEndToEnd(unittest.TestCase):
    def test_happy_path_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "change-specs", "feat-thing.md"), (
                "---\nid: 0001\nstatus: accepted\ndate: 2026-08-14\ntier: normal\n"
                "blast_radius:\n  - engine/setup/**\n---\nbody\n"
            ))
            _write(os.path.join(d, "engine", "setup", "thing.py"), "x = 1\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "feature")
            head = _head_sha(d)
            rc = subprocess.run(
                [sys.executable, CHK, "--root", d, "--base", base, "--head", head,
                 "--branch", "feat/thing"],
                capture_output=True, text=True,
            )
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)

    def test_missing_spec_exits_one_and_names_needed_fields(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "engine", "setup", "thing.py"), "x = 1\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "feature, no spec")
            head = _head_sha(d)
            rc = subprocess.run(
                [sys.executable, CHK, "--root", d, "--base", base, "--head", head,
                 "--branch", "feat/thing"],
                capture_output=True, text=True,
            )
            self.assertEqual(rc.returncode, 1)
            self.assertIn("change-specs/feat-thing.md", rc.stderr)
            self.assertIn("blast_radius", rc.stderr)

    def test_blast_radius_violation_names_offending_path(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "change-specs", "feat-thing.md"), (
                "---\nid: 0001\nstatus: accepted\ndate: 2026-08-14\ntier: normal\n"
                "blast_radius:\n  - engine/setup/**\n---\nbody\n"
            ))
            _write(os.path.join(d, "dashboard", "build.py"), "x = 1\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "feature touching undeclared path")
            head = _head_sha(d)
            rc = subprocess.run(
                [sys.executable, CHK, "--root", d, "--base", base, "--head", head,
                 "--branch", "feat/thing"],
                capture_output=True, text=True,
            )
            self.assertEqual(rc.returncode, 1)
            self.assertIn("dashboard/build.py", rc.stderr)

    def test_doc_only_diff_with_no_spec_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "docs", "NOTES.md"), "notes\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "docs only")
            head = _head_sha(d)
            rc = subprocess.run(
                [sys.executable, CHK, "--root", d, "--base", base, "--head", head,
                 "--branch", "feat/thing"],
                capture_output=True, text=True,
            )
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)

    def test_needs_clarification_marker_exits_one(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "change-specs", "feat-thing.md"), (
                "---\nid: 0001\nstatus: proposed\ndate: 2026-08-14\ntier: normal\n"
                "blast_radius:\n  - engine/setup/**\n---\n[NEEDS CLARIFICATION] what?\n"
            ))
            _write(os.path.join(d, "engine", "setup", "thing.py"), "x = 1\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "feature")
            head = _head_sha(d)
            rc = subprocess.run(
                [sys.executable, CHK, "--root", d, "--base", base, "--head", head,
                 "--branch", "feat/thing"],
                capture_output=True, text=True,
            )
            self.assertEqual(rc.returncode, 1)
            self.assertIn("NEEDS CLARIFICATION", rc.stderr)

    def test_no_base_ref_available_exits_zero(self):
        """Not a pull_request event (e.g. plain push) - nothing to diff against."""
        with tempfile.TemporaryDirectory() as d:
            _init_repo(d)
            rc = subprocess.run(
                [sys.executable, CHK, "--root", d, "--head", "HEAD", "--branch", "main"],
                capture_output=True, text=True,
            )
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)


class TestTierEscalation(unittest.TestCase):
    """F7/#253: a spec may not declare a tier lower than its paths require.

    Over-declaring is always fine -- the ratchet turns one way. These test the
    pure helper; the CLI cases below prove it reaches the exit code.
    """

    def setUp(self):
        self.reg = np_risk_tiers.load()

    def _problems(self, declared, files):
        return spec_guard.tier_problems(declared, files, self.reg)

    def test_correct_declaration_is_clean(self):
        self.assertEqual(
            self._problems("high", ["engine/nervepack_engine/hooks/x.py"]), [])

    def test_under_declaring_is_flagged(self):
        problems = self._problems("standard", ["engine/nervepack_engine/hooks/x.py"])
        self.assertEqual(len(problems), 1)

    def test_the_flag_names_the_path_that_forced_the_tier(self):
        """A tier failure that does not say WHICH file caused it is unactionable
        -- the author has to bisect their own diff against a glob list."""
        problems = self._problems("normal", ["docs/a.md",
                                             "engine/nervepack_engine/hooks/x.py"])
        self.assertIn("hooks/x.py", problems[0])

    def test_over_declaring_is_clean(self):
        self.assertEqual(self._problems("high", ["docs/a.md"]), [])


class TestExemptionUsesTheRegistry(unittest.TestCase):
    """The EXEMPT_GLOBS heuristic is gone; exemption is now 'every path is
    standard tier', which is what np-spec-guard.py's own comment asked for."""

    def test_a_hook_change_is_not_exempt(self):
        self.assertFalse(
            spec_guard.is_exempt(".", ["engine/nervepack_engine/hooks/drift_guard.py"]))

    def test_the_registry_itself_is_not_exempt(self):
        """Editing the tier policy must never be a spec-free change."""
        self.assertFalse(spec_guard.is_exempt(".", ["engine/setup/risk-tiers.json"]))


class TestCliTierEscalation(unittest.TestCase):
    def test_under_declared_tier_exits_one_and_names_the_path(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _git(d, "checkout", "-q", "-b", "feat/x")
            _write(os.path.join(d, "engine", "nervepack_engine", "hooks", "h.py"), "x\n")
            _write(os.path.join(d, "change-specs", "feat-x.md"),
                   "---\nid: 0001\nstatus: proposed\ndate: 2026-01-01\n"
                   "tier: standard\nblast_radius:\n  - engine/**\n  - change-specs/**\n---\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "under-declared")
            r = subprocess.run(
                [sys.executable, CHK, "--root", d, "--base", base,
                 "--head", _head_sha(d), "--branch", "feat/x"],
                capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("hooks/h.py", r.stderr)
        self.assertIn("high", r.stderr)

    def test_correctly_declared_high_tier_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _git(d, "checkout", "-q", "-b", "feat/y")
            _write(os.path.join(d, "engine", "nervepack_engine", "hooks", "h.py"), "x\n")
            _write(os.path.join(d, "change-specs", "feat-y.md"),
                   "---\nid: 0001\nstatus: proposed\ndate: 2026-01-01\n"
                   "tier: high\nblast_radius:\n  - engine/**\n  - change-specs/**\n---\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "correctly declared")
            r = subprocess.run(
                [sys.executable, CHK, "--root", d, "--base", base,
                 "--head", _head_sha(d), "--branch", "feat/y"],
                capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
