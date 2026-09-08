# np-test: spec-review | failure
"""Tests for hooks.spec_review -- the PreToolUse spec-review gate (spec 0027).

This hook interrupts, so the paths where it must NOT interrupt carry more
weight than the one where it must. Every test asserting an ask has a sibling
asserting the gate stays out of the way.
"""
import json
import os
import sys
import time
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
_ENGINE_PARENT = os.path.normpath(os.path.join(_ENGINE_DIR, ".."))
for _p in (_ENGINE_PARENT, _ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hooks import spec_review  # noqa: E402

SPEC = (
    "---\n"
    "id: 0027\n"
    "status: accepted\n"
    "date: 2026-09-07\n"
    "tier: high\n"
    "blast_radius:\n"
    "  - engine/**\n"
    "---\n\n# 0027: a spec\n"
)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.log = os.path.join(self.tmp, "spec-review.log")
        self.seen = os.path.join(self.tmp, "seen")
        os.environ["NP_SPEC_REVIEW_LOG"] = self.log
        os.environ["NP_SPEC_REVIEW_DIR"] = self.seen
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.repo, "change-specs"))
        os.makedirs(os.path.join(self.repo, "engine"))
        self._head("ref: refs/heads/feat-spec-review-gate\n")
        self._spec("feat-spec-review-gate", SPEC)

    def tearDown(self):
        os.environ.pop("NP_SPEC_REVIEW_LOG", None)
        os.environ.pop("NP_SPEC_REVIEW_DIR", None)

    def _head(self, text):
        with open(os.path.join(self.repo, ".git", "HEAD"), "w",
                  encoding="utf-8") as fh:
            fh.write(text)

    def _spec(self, slug, text):
        path = os.path.join(self.repo, "change-specs", slug + ".md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _plan(self, name, text="# a plan\n", age_days=0):
        d = os.path.join(self.repo, "docs", "superpowers", "plans")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if age_days:
            old = time.time() - age_days * 86400
            os.utime(path, (old, old))
        return path

    def _run(self, rel_path, sid="s1", gates_on=True, review_on=True,
             tool="Edit", repo=None):
        root = repo or self.repo
        payload = json.dumps({
            "session_id": sid,
            "tool_name": tool,
            "tool_input": {"file_path": os.path.join(root, rel_path)},
        })
        states = {"gates": gates_on, "gates.spec_review": review_on}
        with mock.patch("np_toggle.enabled",
                        side_effect=lambda f: states.get(f, True)):
            return spec_review.run(payload)

    def _decision(self, out):
        if not out:
            return ""
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]

    def _reason(self, out):
        blob = json.loads(out)["hookSpecificOutput"]
        return blob.get("permissionDecisionReason") or ""

    def _log_text(self):
        if not os.path.isfile(self.log):
            return ""
        with open(self.log, encoding="utf-8") as fh:
            return fh.read()


class TestAsksBeforeImplementation(_Base):
    def test_first_implementation_edit_asks(self):
        out = self._run("engine/thing.py")
        self.assertEqual(self._decision(out), "ask")
        self.assertIn("change-specs/feat-spec-review-gate.md", self._reason(out))

    def test_ask_is_logged(self):
        self._run("engine/thing.py")
        self.assertIn("spec-review ASK", self._log_text())

    def test_second_edit_same_session_is_silent(self):
        self.assertEqual(self._decision(self._run("engine/thing.py")), "ask")
        self.assertEqual(self._run("engine/other.py"), "")

    def test_a_different_session_asks_again(self):
        self._run("engine/thing.py", sid="s1")
        self.assertEqual(self._decision(self._run("engine/thing.py", sid="s2")),
                         "ask")

    def test_editing_the_spec_invalidates_the_receipt(self):
        self.assertEqual(self._decision(self._run("engine/thing.py")), "ask")
        self.assertEqual(self._run("engine/other.py"), "")
        path = self._spec("feat-spec-review-gate", SPEC + "\n## Deviations\n")
        future = time.time() + 10
        os.utime(path, (future, future))
        self.assertEqual(self._decision(self._run("engine/third.py")), "ask")


class TestAuthoringIsNeverGated(_Base):
    def test_writing_the_change_spec_is_silent(self):
        self.assertEqual(
            self._run("change-specs/feat-spec-review-gate.md", tool="Write"), "")

    def test_writing_a_superpowers_spec_is_silent(self):
        self.assertEqual(
            self._run("docs/superpowers/specs/2026-09-07-x-design.md",
                      tool="Write"), "")

    def test_writing_a_superpowers_plan_is_silent(self):
        self.assertEqual(
            self._run("docs/superpowers/plans/2026-09-07-x.md", tool="Write"), "")

    def test_authoring_leaves_no_receipt(self):
        self._run("change-specs/feat-spec-review-gate.md", tool="Write")
        self.assertEqual(self._decision(self._run("engine/thing.py")), "ask")


class TestToggles(_Base):
    def test_gates_off_is_silent(self):
        self.assertEqual(self._run("engine/thing.py", gates_on=False), "")

    def test_spec_review_off_is_silent(self):
        self.assertEqual(self._run("engine/thing.py", review_on=False), "")

    def test_an_override_is_logged(self):
        self._run("engine/thing.py", review_on=False)
        self.assertIn("spec-review OFF", self._log_text())


class TestNoJurisdiction(_Base):
    def test_outside_a_repo_is_silent(self):
        loose = os.path.join(self.tmp, "loose")
        os.makedirs(loose)
        self.assertEqual(self._run("x.py", repo=loose), "")

    def test_no_governing_document_is_silent(self):
        os.remove(os.path.join(self.repo, "change-specs",
                               "feat-spec-review-gate.md"))
        self.assertEqual(self._run("engine/thing.py"), "")

    def test_detached_head_is_silent(self):
        self._head("0123456789abcdef0123456789abcdef01234567\n")
        self.assertEqual(self._run("engine/thing.py"), "")

    def test_a_relative_path_is_silent(self):
        payload = json.dumps({"session_id": "s1", "tool_name": "Edit",
                              "tool_input": {"file_path": "engine/thing.py"}})
        self.assertEqual(spec_review.run(payload), "")

    def test_malformed_payload_is_silent(self):
        self.assertEqual(spec_review.run("not json"), "")
        self.assertEqual(spec_review.run("[]"), "")
        self.assertEqual(spec_review.run(""), "")


class TestPlanFallback(_Base):
    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.repo, "change-specs",
                               "feat-spec-review-gate.md"))

    def test_a_recent_plan_governs_when_no_change_spec_exists(self):
        self._plan("2026-09-07-x.md")
        out = self._run("engine/thing.py")
        self.assertEqual(self._decision(out), "ask")
        self.assertIn("docs/superpowers/plans/2026-09-07-x.md",
                      self._reason(out))

    def test_a_stale_plan_is_ignored(self):
        self._plan("2026-01-01-old.md", age_days=90)
        self.assertEqual(self._run("engine/thing.py"), "")

    def test_the_newest_plan_wins(self):
        self._plan("2026-09-01-old.md", age_days=3)
        self._plan("2026-09-07-new.md")
        self.assertIn("2026-09-07-new.md", self._reason(self._run("engine/x.py")))


class TestFailsOpen(_Base):
    def test_an_unwritable_receipt_dir_still_allows(self):
        os.environ["NP_SPEC_REVIEW_DIR"] = os.path.join(self.repo, "engine",
                                                        "thing.py", "nope")
        out = self._run("engine/thing.py")
        self.assertEqual(self._decision(out), "ask")

    def test_an_unwritable_log_does_not_change_the_decision(self):
        os.environ["NP_SPEC_REVIEW_LOG"] = os.path.join(
            self.repo, "engine", "thing.py", "nope", "x.log")
        self.assertEqual(self._decision(self._run("engine/thing.py")), "ask")


class TestReceiptPathIsContained(_Base):
    """The receipt filename is built from a payload-supplied session id. No id
    may name a path outside the cache directory -- on Windows the separator is a
    backslash, and "." or ".." name directories on both."""

    def _path(self, sid):
        return os.path.realpath(spec_review._receipt_path(sid))

    def test_a_normal_id_is_kept_verbatim(self):
        self.assertEqual(os.path.basename(self._path("abc-123.def")),
                         "abc-123.def")

    def test_every_hostile_id_stays_inside_the_directory(self):
        root = os.path.realpath(self.seen)
        for sid in ("../../etc/passwd", "..", ".", "a/../../b",
                    "a\\..\\..\\windows", "....//....//x", "/abs/path"):
            got = self._path(sid)
            self.assertEqual(os.path.dirname(got), root, sid)
            self.assertNotIn(os.sep + "..", got, sid)

    def test_an_empty_or_dotted_id_still_names_a_file(self):
        for sid in ("", "...", "/"):
            self.assertTrue(os.path.basename(self._path(sid)), repr(sid))

    def test_a_hostile_id_round_trips_as_a_receipt(self):
        out = self._run("engine/thing.py", sid="../../escape")
        self.assertEqual(self._decision(out), "ask")
        self.assertEqual(self._run("engine/other.py", sid="../../escape"), "")


if __name__ == "__main__":
    unittest.main()
