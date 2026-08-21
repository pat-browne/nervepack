#!/usr/bin/env python3
# np-test: tier-gate | happy
"""Contract test for np-tier-gate.py -- differential gating by tier (F8/#254).

Covers the verdict reader, the fail-open and fail-closed boundaries, and the
CLI end-to-end against a fixture repo. The policy itself is tested in
test_tier_policy.py; this file tests the I/O around it.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHK = os.path.abspath(os.path.join(HERE, "..", "..", "np-tier-gate.py"))

_spec = importlib.util.spec_from_file_location("tier_gate", CHK)
tier_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tier_gate)

sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
import np_tier_policy  # noqa: E402

DETERMINISTIC = list(np_tier_policy.DETERMINISTIC_GATES)


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
    return subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _head_sha(d):
    return subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _verdicts_dir(d, verdicts):
    """A directory shaped like download-artifact's merge-multiple output."""
    out = os.path.join(d, "verdicts")
    os.makedirs(out, exist_ok=True)
    for gate, verdict in verdicts.items():
        with open(os.path.join(out, "gate-verdict-%s.json" % gate), "w") as f:
            json.dump({"schema": "nervepack.gate-verdict/1", "gate": gate,
                       "verdict": verdict, "reason": "t", "evidence_ref": "u",
                       "rules_sha": "s"}, f)
    return out


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _run(d, base, head, branch, vdir, out=None):
    argv = [sys.executable, CHK, "--root", d, "--base", base, "--head", head,
            "--branch", branch, "--verdicts-dir", vdir]
    if out:
        argv += ["--out", out]
    return subprocess.run(argv, capture_output=True, text=True)


class TestReadVerdicts(unittest.TestCase):
    def test_keys_on_the_gate_field_not_the_filename(self):
        """The filename is a workflow-authored artifact name; the `gate` field
        is what the emitting job declared it was gating. If this ever reads the
        filename, renaming an artifact silently drops a required gate."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gate-verdict-whatever.json")
            with open(path, "w") as f:
                json.dump({"gate": "regression", "verdict": "PASSED"}, f)
            self.assertEqual(tier_gate.read_verdicts(d), {"regression": "PASSED"})

    def test_a_missing_directory_reads_as_no_verdicts(self):
        self.assertEqual(tier_gate.read_verdicts("/nonexistent/nowhere"), {})

    def test_unparseable_json_is_skipped_not_fatal(self):
        """A corrupt artifact must not replace np_tier_policy's specific
        'gate X produced no verdict' message with a stack trace."""
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "gate-verdict-broken.json"), "{not json")
            with open(os.path.join(d, "gate-verdict-ok.json"), "w") as f:
                json.dump({"gate": "syntax", "verdict": "PASSED"}, f)
            self.assertEqual(tier_gate.read_verdicts(d), {"syntax": "PASSED"})

    def test_a_file_missing_either_field_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "gate-verdict-half.json"), "w") as f:
                json.dump({"gate": "syntax"}, f)
            self.assertEqual(tier_gate.read_verdicts(d), {})

    def test_files_that_are_not_gate_verdicts_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "tier-policy.json"), "w") as f:
                json.dump({"gate": "tier-gate", "verdict": "PASSED"}, f)
            self.assertEqual(tier_gate.read_verdicts(d), {})


class TestCliEndToEnd(unittest.TestCase):
    def test_a_docs_only_diff_is_standard_and_clean(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "docs", "NOTES.md"), "notes\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "docs")
            vdir = _verdicts_dir(d, {g: "PASSED" for g in DETERMINISTIC})
            out = os.path.join(d, "policy.json")
            rc = _run(d, base, _head_sha(d), "feat/thing", vdir, out)
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            policy = _read_json(out)
            self.assertEqual(policy["tier"], "standard")
            self.assertTrue(policy["auto_merge_eligible"])

    def test_a_hook_change_is_high_and_needs_a_rollback_plan(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "engine", "hooks", "thing.py"), "x = 1\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "hook")
            vdir = _verdicts_dir(
                d, dict({g: "PASSED" for g in DETERMINISTIC},
                        **{"spec-guard": "PASSED", "diff-review": "PASSED"}))
            out = os.path.join(d, "policy.json")
            rc = _run(d, base, _head_sha(d), "feat/thing", vdir, out)
            self.assertEqual(rc.returncode, 1)
            # No spec at all: the message says so rather than asking for a
            # section in a file that does not exist.
            self.assertIn("no change spec was found", rc.stderr)
            policy = _read_json(out)
            self.assertEqual(policy["tier"], "high")
            self.assertFalse(policy["auto_merge_eligible"])

    def test_a_high_change_with_a_rollback_plan_and_a_run_lens_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "engine", "hooks", "thing.py"), "x = 1\n")
            _write(os.path.join(d, "change-specs", "feat-thing.md"),
                   "---\ntier: high\n---\n\n## Rollback\n\nRevert the commit.\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "hook with spec")
            vdir = _verdicts_dir(
                d, dict({g: "PASSED" for g in DETERMINISTIC},
                        **{"spec-guard": "PASSED", "diff-review": "FAILED"}))
            rc = _run(d, base, _head_sha(d), "feat/thing", vdir)
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)

    def test_the_policy_names_the_path_that_forced_the_tier(self):
        """A tier failure that does not name the file which forced it makes the
        author bisect their own diff against a glob list."""
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "engine", "hooks", "thing.py"), "x = 1\n")
            _write(os.path.join(d, "docs", "x.md"), "x\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "mixed")
            vdir = _verdicts_dir(d, {g: "PASSED" for g in DETERMINISTIC})
            out = os.path.join(d, "policy.json")
            _run(d, base, _head_sha(d), "feat/thing", vdir, out)
            sources = [s["path"] for s in _read_json(out)["tier_source"]]
            self.assertEqual(sources, ["engine/hooks/thing.py"])

    def test_the_spec_file_itself_does_not_change_the_tier(self):
        """spec-guard excludes it too. The two gates must read the same list."""
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "change-specs", "feat-thing.md"),
                   "---\ntier: standard\n---\nbody\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "spec only")
            vdir = _verdicts_dir(d, {g: "PASSED" for g in DETERMINISTIC})
            out = os.path.join(d, "policy.json")
            rc = _run(d, base, _head_sha(d), "feat/thing", vdir, out)
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            self.assertEqual(_read_json(out)["tier_source"], [])

    def test_a_missing_required_verdict_fails_and_names_the_gate(self):
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "docs", "NOTES.md"), "notes\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "docs")
            vdir = _verdicts_dir(
                d, {g: "PASSED" for g in DETERMINISTIC if g != "regression"})
            rc = _run(d, base, _head_sha(d), "feat/thing", vdir)
            self.assertEqual(rc.returncode, 1)
            self.assertIn("regression", rc.stderr)

    def test_an_unreadable_spec_fails_and_says_which_file(self):
        """A spec that exists and cannot be read must not report as a spec that
        does not exist. The author would go looking for a missing file that is
        sitting right in front of them."""
        with tempfile.TemporaryDirectory() as d:
            base = _init_repo(d)
            _write(os.path.join(d, "engine", "hooks", "thing.py"), "x = 1\n")
            spec = os.path.join(d, "change-specs", "feat-thing.md")
            # Invalid UTF-8: a real encoding failure, and the one case that
            # needs no permission games to reproduce as a non-root user.
            os.makedirs(os.path.dirname(spec), exist_ok=True)
            with open(spec, "wb") as f:
                f.write(b"---\ntier: high\n---\n\n## Rollback\n\n\xff\xfe bad\n")
            _git(d, "add", "-A")
            _git(d, "commit", "-q", "-m", "spec with invalid utf-8")
            vdir = _verdicts_dir(d, {g: "PASSED" for g in DETERMINISTIC})
            rc = _run(d, base, _head_sha(d), "feat/thing", vdir)
            self.assertEqual(rc.returncode, 1)
            self.assertIn("cannot read", rc.stderr)
            self.assertIn("feat-thing.md", rc.stderr)
            self.assertNotIn("no change spec was found", rc.stderr)

    def test_a_broken_registry_is_a_policy_failure_not_a_skip(self):
        """np_risk_tiers.load already wraps OSError and ValueError in
        RegistryError, so catching only RegistryError here is complete. This
        test is what makes that true rather than assumed."""
        import np_risk_tiers
        for bad in ("", "{not json", '{"schema": 99}', '[]'):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "risk-tiers.json")
                _write(path, bad)
                with self.assertRaises(np_risk_tiers.RegistryError):
                    np_risk_tiers.load(path)
        with self.assertRaises(np_risk_tiers.RegistryError):
            np_risk_tiers.load(os.path.join("/nonexistent", "risk-tiers.json"))

    def test_no_base_ref_exits_zero(self):
        """Not a pull_request event. Same contract as spec-guard."""
        rc = subprocess.run([sys.executable, CHK, "--root", ".", "--base", ""],
                            capture_output=True, text=True,
                            env=dict(os.environ, GITHUB_BASE_REF=""))
        self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
        self.assertIn("not a pull_request", rc.stdout)

    def test_an_unresolvable_ref_fails_open(self):
        """A shallow clone is an infrastructure problem, not a policy one.
        Failing closed here would block every PR on a checkout misconfiguration."""
        with tempfile.TemporaryDirectory() as d:
            _init_repo(d)
            rc = _run(d, "no-such-ref", "HEAD", "feat/thing", os.path.join(d, "v"))
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)


if __name__ == "__main__":
    unittest.main()
