"""Tests for nervepack_engine.hooks.lesson_guard — the Python port of
lesson-guard.sh. Ports all 7 scenarios from
engine/setup/tests/lessons/test_lesson_guard.sh plus all 4 scenarios from
engine/setup/tests/lessons/test_enforcement_continuity.sh (11 bash scenarios
combined) plus 2 new cases (missing-index via layer_dir default path;
unknown-tool_name silence)."""
import hashlib
import json
import os
import sys
import unittest
from unittest import mock

# _HERE is engine/setup/tests/nervepack_engine — two levels up is engine/setup
# (needed so lesson_guard.py's own `import np_content`/`np_toggle` resolve when
# this test imports it directly, bypassing cli.py's own sys.path fixup), three
# levels up is engine/ (needed for `import nervepack_engine`).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestLessonGuard(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.lessons = os.path.join(self.tmp, "lessons")
        os.makedirs(self.lessons, exist_ok=True)
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.state, exist_ok=True)
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("lessons|shared|runtime|on|\n")
        self.toggles_local = os.path.join(self.tmp, "local")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": self.toggles_local,
            "EPISODIC_LESSON_DIR": self.lessons,
            "EPISODIC_STATE_DIR": self.state,
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, content):
        with open(os.path.join(self.lessons, name), "w") as fh:
            fh.write(content)

    def _run(self, payload):
        from nervepack_engine.hooks import lesson_guard
        return lesson_guard.run(json.dumps(payload))

    # --- ported from test_lesson_guard.sh ---
    def test_1_warn_gate_allows_with_context(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| bulk-rename | sed -i .*s[#/] | warn | rename, sed |\n"
            "| nuke | rm -rf | ask | delete, cleanup |\n")
        self._write("bulk-rename.md",
            "---\nname: bulk-rename\nprovenance: failure\n---\n"
            "**Do:** guarded single pass; residual-grep verify.\n"
            "**Avoid:** blanket bare-word replace.\n")
        out = self._run({"tool_name": "Bash", "tool_input": {"command": 'sed -i "s#a#b#" f'}})
        self.assertTrue(out)
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "allow")
        self.assertIn("guarded single pass", d["additionalContext"])

    def test_2_ask_gate_blocks_with_reason(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| nuke | rm -rf | ask | delete, cleanup |\n")
        self._write("nuke.md",
            "---\nname: nuke\nprovenance: failure\n---\n"
            "**Avoid:** rm -rf without an explicit, checked path.\n")
        out = self._run({"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/x"}})
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "ask")
        self.assertIn("rm -rf without an explicit", d["permissionDecisionReason"])

    def test_3_non_matching_command_silent(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| nuke | rm -rf | ask | delete, cleanup |\n")
        out = self._run({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
        self.assertEqual(out, "")

    def test_4_missing_index_fails_open(self):
        with mock.patch.dict(os.environ, {"EPISODIC_LESSON_DIR": os.path.join(self.tmp, "none")}):
            out = self._run({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
        self.assertEqual(out, "")

    def test_5_phase2_armed_marker_fires_once_then_removed(self):
        # Bash requires INDEX.md to exist even for the Phase 2 (non-Bash
        # tool_name) path -- the guard's `[[ -f "$INDEX" ]] || exit 0` gate
        # runs unconditionally before either phase, so a Phase-2-only fixture
        # with no INDEX.md would fail open in the real bash hook too.
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n")
        self._write("sec-review.md",
            "---\nname: sec-review\nprovenance: failure\n"
            "enforce:\n  tool_name_match: \"Read\"\n  gate: ask\n---\n"
            "**Do:** invoke the skill first.\n")
        open(os.path.join(self.state, "s1-sec-review-gate-armed"), "a").close()
        out = self._run({"tool_name": "Read", "session_id": "s1", "tool_input": {"file_path": "/some/file.py"}})
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "ask")
        self.assertFalse(os.path.exists(os.path.join(self.state, "s1-sec-review-gate-armed")))

    def test_6_phase2_unarmed_read_silent(self):
        # Same INDEX.md requirement as test_5 -- without it the guard would
        # exit before Phase 2 for an unrelated reason (missing index), not
        # because the marker is unarmed, which is what this test targets.
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n")
        self._write("sec-review.md",
            "---\nname: sec-review\nprovenance: failure\n"
            "enforce:\n  tool_name_match: \"Read\"\n  gate: ask\n---\n"
            "**Do:** invoke the skill first.\n")
        out = self._run({"tool_name": "Read", "session_id": "s1", "tool_input": {"file_path": "/other/file.py"}})
        self.assertEqual(out, "")

    def test_7_default_path_uses_layer_dir(self):
        tmp2_content = os.path.join(self.tmp, "content2")
        os.makedirs(os.path.join(tmp2_content, "memory", "lessons"), exist_ok=True)
        with open(os.path.join(tmp2_content, "memory", "lessons", "INDEX.md"), "w") as fh:
            fh.write("| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
                      "| force-push | git push.*--force | ask | force, push |\n")
        with open(os.path.join(tmp2_content, "memory", "lessons", "force-push.md"), "w") as fh:
            fh.write("---\nname: force-push\nprovenance: failure\n---\n"
                      "**Avoid:** force-pushing without checking the remote first.\n")
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": tmp2_content}):
            os.environ.pop("EPISODIC_LESSON_DIR", None)
            out = self._run({"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}})
            os.environ["EPISODIC_LESSON_DIR"] = self.lessons
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "ask")
        self.assertIn("force-pushing", d["permissionDecisionReason"])

    # --- ported from test_enforcement_continuity.sh ---
    def test_8_enforced_failure_lesson_asks(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| git | grep -[a-z]*l[a-z]*i | ask | git |\n")
        self._write("git.md",
            "---\nname: x\nprovenance: failure\n---\n"
            "**Symptom:** combined short grep flags like -lin are easy to misread.\n"
            "**Do:** prefer separate long-form flags in scripted/wrapped contexts.\n")
        out = self._run({"tool_name": "Bash", "tool_input": {"command": "grep -lin foo"}, "session_id": "t"})
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "ask")
        self.assertIn("combined short grep flags", d["permissionDecisionReason"])

    def test_9_advisory_success_lesson_never_fires(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| refactor |  |  | refactor |\n")
        out = self._run({"tool_name": "Bash", "tool_input": {"command": "npm test"}, "session_id": "t2"})
        self.assertEqual(out, "")

    def test_10_lessons_enforce_off_silences(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| git | grep -[a-z]*l[a-z]*i | ask | git |\n")
        self._write("git.md", "---\nname: x\nprovenance: failure\n---\n**Do:** x\n")
        with open(self.toggles_local, "w") as fh:
            fh.write("lessons.enforce=off\n")
        out = self._run({"tool_name": "Bash", "tool_input": {"command": "grep -lin foo"}, "session_id": "t3"})
        self.assertEqual(out, "")

    def test_11_lessons_off_silences(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| git | grep -[a-z]*l[a-z]*i | ask | git |\n")
        self._write("git.md", "---\nname: x\nprovenance: failure\n---\n**Do:** x\n")
        with open(self.toggles_local, "w") as fh:
            fh.write("lessons=off\n")
        out = self._run({"tool_name": "Bash", "tool_input": {"command": "grep -lin foo"}, "session_id": "t4"})
        self.assertEqual(out, "")

    # --- new cases beyond the 11 ported scenarios ---
    def test_12_phase1_frontmatter_only_reads_first_block_of_a_merged_file(self):
        # A merged multi-provenance file: block 1 (failure) has enforce.tool_match
        # handled via INDEX.md, not frontmatter -- this test targets Phase 2's
        # _fm_val-equivalent first-block-only restriction directly, using a
        # merged file where ONLY the first block carries tool_name_match.
        # (Same INDEX.md requirement noted in test_5/test_6.)
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n")
        self._write("merged.md",
            "---\nname: merged\nprovenance: failure\n"
            "enforce:\n  tool_name_match: \"Read\"\n  gate: warn\n---\n"
            "**Do:** first block body.\n"
            "---\nname: merged\nprovenance: success\n"
            "enforce:\n  tool_name_match: \"Write\"\n---\n"
            "**Title:** second block body.\n")
        open(os.path.join(self.state, "s5-merged-gate-armed"), "a").close()
        out = self._run({"tool_name": "Read", "session_id": "s5", "tool_input": {"file_path": "/x"}})
        # Must fire using block 1's gate (warn/allow), never see block 2's fields
        d = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(d["permissionDecision"], "allow")

    def test_13_unknown_tool_name_with_no_armed_marker_silent(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| nuke | rm -rf | ask | delete, cleanup |\n")
        out = self._run({"tool_name": "Glob", "session_id": "s6", "tool_input": {}})
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
