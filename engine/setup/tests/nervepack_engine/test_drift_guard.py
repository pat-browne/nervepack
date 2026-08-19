# np-test: drift-guard | failure
"""Tests for hooks.drift_guard -- the PreToolUse spec-drift gate (#249).

This is the second hook in nervepack permitted to block, so the failure-open
paths carry as much weight as the blocking one. Every test that asserts a deny
has a sibling asserting the guard gets out of the way instead of bricking the
session.
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

from hooks import drift_guard  # noqa: E402

SPEC = (
    "---\n"
    "id: 0007\n"
    "status: proposed\n"
    "date: 2026-08-19\n"
    "tier: high\n"
    "blast_radius:\n"
    "  - engine/setup/**\n"
    "  - change-specs/**\n"
    "---\n\n# 0007: a spec\n"
)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.log = os.path.join(self.tmp, "drift-guard.log")
        os.environ["NP_DRIFT_GUARD_LOG"] = self.log
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.repo, "change-specs"))
        self._head("ref: refs/heads/feat/f3-drift-guard\n")
        self._spec("feat-f3-drift-guard", SPEC)

    def tearDown(self):
        os.environ.pop("NP_DRIFT_GUARD_LOG", None)

    def _head(self, text):
        with open(os.path.join(self.repo, ".git", "HEAD"), "w",
                  encoding="utf-8") as fh:
            fh.write(text)

    def _spec(self, slug, text):
        with open(os.path.join(self.repo, "change-specs", slug + ".md"), "w",
                  encoding="utf-8") as fh:
            fh.write(text)

    def _run(self, rel_path, enforce="on", gates_on=True, tool="Edit"):
        payload = json.dumps({
            "session_id": "s1",
            "tool_name": tool,
            "tool_input": {"file_path": os.path.join(self.repo, rel_path)},
        })
        with mock.patch("np_toggle.enabled", side_effect=lambda f: gates_on), \
             mock.patch("np_toggle.param",
                        side_effect=lambda k, d=None:
                        enforce if k == "gates.drift_guard.enforce" else d):
            return drift_guard.run(payload)

    def _decision(self, out):
        if not out:
            return ""
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]

    def _reason(self, out):
        blob = json.loads(out)["hookSpecificOutput"]
        return blob.get("permissionDecisionReason") or blob.get("additionalContext") or ""

    def _log_text(self):
        if not os.path.isfile(self.log):
            return ""
        with open(self.log, encoding="utf-8") as fh:
            return fh.read()


class TestBlocks(_Base):
    def test_path_outside_blast_radius_is_denied(self):
        out = self._run("dashboard/build.py")
        self.assertEqual(self._decision(out), "deny")

    def test_denial_names_the_offending_path(self):
        reason = self._reason(self._run("dashboard/build.py"))
        self.assertIn("dashboard/build.py", reason)

    def test_denial_names_the_spec(self):
        reason = self._reason(self._run("dashboard/build.py"))
        self.assertIn("change-specs/feat-f3-drift-guard.md", reason)

    def test_denial_offers_both_legal_responses(self):
        """Never auto-widen -- but a block with no way forward gets the hook
        deleted, which is the same outcome as never having built it."""
        reason = self._reason(self._run("dashboard/build.py")).lower()
        self.assertIn("deviations", reason)
        self.assertIn("supersede", reason)

    def test_write_is_guarded_as_well_as_edit(self):
        out = self._run("dashboard/build.py", tool="Write")
        self.assertEqual(self._decision(out), "deny")

    def test_deny_is_logged(self):
        self._run("dashboard/build.py")
        self.assertIn("DENY", self._log_text())


class TestAllows(_Base):
    def test_path_inside_blast_radius_passes_silently(self):
        self.assertEqual(self._run("engine/setup/np_toggle.py"), "")

    def test_nested_path_inside_a_recursive_glob_passes(self):
        self.assertEqual(self._run("engine/setup/tests/x/test_y.py"), "")

    def test_the_spec_itself_is_always_writable(self):
        """Recording a Deviation is the sanctioned response to a block. If the
        spec were not in its own radius, the fix would be unreachable."""
        self.assertEqual(self._run("change-specs/feat-f3-drift-guard.md"), "")

    def test_adjudicated_pass_is_logged(self):
        self._run("engine/setup/np_toggle.py")
        self.assertIn("PASS", self._log_text())


class TestEnforceToggle(_Base):
    def test_enforce_off_downgrades_a_deny_to_a_warn(self):
        out = self._run("dashboard/build.py", enforce="off")
        self.assertEqual(self._decision(out), "allow")

    def test_warn_still_names_the_path(self):
        out = self._run("dashboard/build.py", enforce="off")
        self.assertIn("dashboard/build.py", self._reason(out))

    def test_warn_is_logged(self):
        self._run("dashboard/build.py", enforce="off")
        self.assertIn("WARN", self._log_text())

    def test_gates_feature_off_disables_the_hook_entirely(self):
        self.assertEqual(self._run("dashboard/build.py", gates_on=False), "")


class TestFailsOpen(_Base):
    """Fails closed on a policy violation, open on its own error."""

    def test_malformed_payload_allows(self):
        self.assertEqual(drift_guard.run("not json"), "")

    def test_empty_payload_allows(self):
        self.assertEqual(drift_guard.run(""), "")

    def test_payload_without_a_file_path_allows(self):
        payload = json.dumps({"tool_name": "Edit", "tool_input": {}})
        self.assertEqual(drift_guard.run(payload), "")

    def test_path_outside_any_repo_allows(self):
        outside = os.path.realpath(tempfile.mkdtemp())
        payload = json.dumps({"tool_name": "Edit", "tool_input": {
            "file_path": os.path.join(outside, "loose.py")}})
        self.assertEqual(drift_guard.run(payload), "")

    def test_repo_without_a_change_spec_allows(self):
        """The common case on every repo that has not adopted the convention."""
        os.remove(os.path.join(self.repo, "change-specs",
                               "feat-f3-drift-guard.md"))
        self.assertEqual(self._run("dashboard/build.py"), "")

    def test_no_spec_is_not_logged(self):
        """Silence is the point -- a line per edit per session per repo is not
        an audit trail, it is noise that gets the log deleted."""
        os.remove(os.path.join(self.repo, "change-specs",
                               "feat-f3-drift-guard.md"))
        self._run("dashboard/build.py")
        self.assertEqual(self._log_text(), "")

    def test_detached_head_allows(self):
        self._head("9f1a2b3c4d5e6f70819a2b3c4d5e6f7081920304\n")
        self.assertEqual(self._run("dashboard/build.py"), "")

    def test_unreadable_head_allows(self):
        os.remove(os.path.join(self.repo, ".git", "HEAD"))
        self.assertEqual(self._run("dashboard/build.py"), "")

    def test_spec_with_no_blast_radius_warns_rather_than_denying(self):
        """A spec that declares no radius is a spec-authoring error, and
        spec-guard already fails the PR for it. Denying every edit in the repo
        over it would brick the session -- the failure mode that gets a guard
        deleted, after which nothing is enforced at all."""
        self._spec("feat-f3-drift-guard", "---\nid: 0007\ntier: high\n---\n")
        out = self._run("dashboard/build.py")
        self.assertEqual(self._decision(out), "allow")

    def test_unwritable_log_does_not_break_the_decision(self):
        os.environ["NP_DRIFT_GUARD_LOG"] = os.path.join(
            self.tmp, "no", "such", "dir", "x.log")
        os.makedirs(os.path.join(self.tmp, "no"))
        open(os.path.join(self.tmp, "no", "such"), "w").close()  # a FILE, not a dir
        out = self._run("dashboard/build.py")
        self.assertEqual(self._decision(out), "deny")


if __name__ == "__main__":
    unittest.main()
