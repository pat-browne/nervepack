"""Tests for nervepack_engine.hooks.lesson_recall — the Python port of
lesson-recall.sh. Ports all 4 scenarios from
engine/setup/tests/lessons/test_lesson_recall.sh and all 4 from
engine/setup/tests/lessons/test_lesson_recall_layers.sh (8 bash scenarios
combined) plus 1 new case (fires-at-most-max-prompts-times)."""
# NOTE: test_9 (team-only) is a bash-scenario port, not a "new case" — it was
# missing from the original port and added later to complete the 4-scenario
# team/personal merge-mode coverage (override, concatenate, team-only, no-team).
import json
import os
import sys
import unittest
from unittest import mock

# _HERE is engine/setup/tests/nervepack_engine — two levels up is engine/setup
# (needed so lesson_recall.py's own `import np_content`/`np_toggle` resolve when
# this test imports it directly, bypassing cli.py's own sys.path fixup), three
# levels up is engine/ (needed for `import nervepack_engine`).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestLessonRecall(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.lessons = os.path.join(self.tmp, "lessons")
        os.makedirs(self.lessons, exist_ok=True)
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("lessons|shared|runtime|on|\nteam|shared|runtime|on|\n")
        self.toggles_local = os.path.join(self.tmp, "local")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": self.toggles_local,
            "EPISODIC_LESSON_DIR": self.lessons,
            "EPISODIC_STATE_DIR": os.path.join(self.tmp, "state"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, name, content):
        with open(os.path.join(self.lessons, name), "w") as fh:
            fh.write(content)

    def _run(self, sid, prompt):
        from nervepack_engine.hooks import lesson_recall
        return lesson_recall.run(json.dumps({"session_id": sid, "prompt": prompt}))

    # --- ported from test_lesson_recall.sh ---
    def test_1_dual_provenance_both_injected_with_framing(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| bulk-rename |  | warn | rename, sed |\n"
            "| deploydance |  |  | deploy, rename |\n")
        self._write("bulk-rename.md",
            "---\nname: bulk-rename\nprovenance: failure\n---\n"
            "**Do:** guarded single pass; residual-grep verify.\n"
            "**Avoid:** blanket bare-word replace.\n")
        self._write("deploydance.md",
            "---\nname: deploydance\nprovenance: success\n---\n"
            "**Title:** Mirror the proven deploy dance\n"
            "**When:** shipping a rename-heavy release\n"
            "**Do:** run the checklist before touching prod.\n")
        out = self._run("s1", "need to do a bulk rename before we deploy")
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("bulk-rename", ctx.lower())
        self.assertIn("guarded single pass", ctx)
        self.assertRegex(ctx.lower(), "past failure")
        self.assertIn("deploydance", ctx.lower())
        self.assertIn("Mirror the proven deploy dance", ctx)
        self.assertRegex(ctx.lower(), "worked")

    def test_2_non_matching_prompt_silent(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| bulk-rename |  | warn | rename, sed |\n")
        out = self._run("s2", "what is the weather today")
        self.assertEqual(out, "")

    def test_3_merged_single_file_both_provenances(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| gitflow | git merge | warn | merge |\n")
        self._write("gitflow.md",
            "---\nname: gitflow\nprovenance: failure\n---\n"
            "**Do:** rebase onto main before merging.\n"
            "**Avoid:** merging without rebasing first.\n"
            "---\nname: gitflow\nprovenance: success\n---\n"
            "**Title:** Squash-merge feature branches\n"
            "**When:** landing a reviewed feature branch\n"
            "**Do:** squash-merge to keep history linear.\n")
        out = self._run("s3", "about to merge this branch")
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("rebase onto main", ctx)
        self.assertIn("Squash-merge feature branches", ctx)
        self.assertRegex(ctx.lower(), "past failure")
        self.assertRegex(ctx.lower(), "worked")

    def test_4_armed_marker_written_for_tool_name_match_lesson(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| sec-review |  | ask | security, review |\n")
        self._write("sec-review.md",
            "---\nname: sec-review\nprovenance: failure\n"
            "enforce:\n  tool_match: \"\"\n  tool_name_match: \"Read\"\n  gate: ask\n---\n"
            "**Do:** invoke the skill first.\n")
        self._run("s4", "please do a security review of this code")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "state", "s4-sec-review-gate-armed")))

    # --- ported from test_lesson_recall_layers.sh ---
    def test_5_override_mode_team_wins(self):
        personal_root = os.path.join(self.tmp, "personal")
        team = os.path.join(self.tmp, "team")
        with open(self.toggles_local, "w") as fh:
            fh.write("team.merge=override\n")
        for root, label in ((personal_root, "PERSONAL"), (team, "TEAM")):
            layer = os.path.join(root, "memory", "lessons")
            os.makedirs(layer, exist_ok=True)
            with open(os.path.join(layer, "INDEX.md"), "w") as fh:
                fh.write("| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
                          "| gitflow |  | warn | merge |\n")
            with open(os.path.join(layer, "gitflow.md"), "w") as fh:
                fh.write("---\nname: gitflow\nprovenance: failure\n---\n**Do:** %s lesson\n" % label)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": personal_root, "NP_TEAM_DIR": team}):
            os.environ.pop("EPISODIC_LESSON_DIR", None)
            out = self._run("s5", "about to merge")
            os.environ["EPISODIC_LESSON_DIR"] = self.lessons
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("TEAM lesson", ctx)
        self.assertNotIn("PERSONAL lesson", ctx)

    def test_6_concatenate_mode_both(self):
        personal_root = os.path.join(self.tmp, "personal")
        team = os.path.join(self.tmp, "team")
        with open(self.toggles_local, "w") as fh:
            fh.write("team.merge=concatenate\n")
        for root, label in ((personal_root, "PERSONAL"), (team, "TEAM")):
            layer = os.path.join(root, "memory", "lessons")
            os.makedirs(layer, exist_ok=True)
            with open(os.path.join(layer, "INDEX.md"), "w") as fh:
                fh.write("| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
                          "| gitflow |  | warn | merge |\n")
            with open(os.path.join(layer, "gitflow.md"), "w") as fh:
                fh.write("---\nname: gitflow\nprovenance: failure\n---\n**Do:** %s lesson\n" % label)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": personal_root, "NP_TEAM_DIR": team}):
            os.environ.pop("EPISODIC_LESSON_DIR", None)
            out = self._run("s6", "about to merge")
            os.environ["EPISODIC_LESSON_DIR"] = self.lessons
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("TEAM lesson", ctx)
        self.assertIn("PERSONAL lesson", ctx)

    def test_7_no_team_configured_personal_only(self):
        personal_root = os.path.join(self.tmp, "personal")
        layer = os.path.join(personal_root, "memory", "lessons")
        os.makedirs(layer, exist_ok=True)
        with open(os.path.join(layer, "INDEX.md"), "w") as fh:
            fh.write("| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
                      "| gitflow |  | warn | merge |\n")
        with open(os.path.join(layer, "gitflow.md"), "w") as fh:
            fh.write("---\nname: gitflow\nprovenance: failure\n---\n**Do:** PERSONAL lesson\n")
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": personal_root}):
            os.environ.pop("EPISODIC_LESSON_DIR", None)
            os.environ.pop("NP_TEAM_DIR", None)
            out = self._run("s7", "about to merge")
            os.environ["EPISODIC_LESSON_DIR"] = self.lessons
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("PERSONAL lesson", ctx)

    # --- new case ---
    def test_8_fires_at_most_max_prompts_times_per_session(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| bulk-rename |  | warn | rename |\n")
        self._write("bulk-rename.md", "---\nname: bulk-rename\nprovenance: failure\n---\n**Do:** x\n")
        with mock.patch.dict(os.environ, {"EPISODIC_RECALL_MAX": "2"}):
            out1 = self._run("s9", "rename this")
            out2 = self._run("s9", "rename that")
            out3 = self._run("s9", "rename again")
        self.assertTrue(out1)
        self.assertTrue(out2)
        self.assertEqual(out3, "")

    # --- ported from test_lesson_recall_layers.sh (team-only, previously missing) ---
    def test_9_team_only_mode_only_team_shown(self):
        personal_root = os.path.join(self.tmp, "personal")
        team = os.path.join(self.tmp, "team")
        with open(self.toggles_local, "w") as fh:
            fh.write("team.merge=team-only\n")
        for root, label in ((personal_root, "PERSONAL"), (team, "TEAM")):
            layer = os.path.join(root, "memory", "lessons")
            os.makedirs(layer, exist_ok=True)
            with open(os.path.join(layer, "INDEX.md"), "w") as fh:
                fh.write("| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
                          "| gitflow |  | warn | merge |\n")
            with open(os.path.join(layer, "gitflow.md"), "w") as fh:
                fh.write("---\nname: gitflow\nprovenance: failure\n---\n**Do:** %s lesson\n" % label)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": personal_root, "NP_TEAM_DIR": team}):
            os.environ.pop("EPISODIC_LESSON_DIR", None)
            out = self._run("s10", "about to merge")
            os.environ["EPISODIC_LESSON_DIR"] = self.lessons
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("TEAM lesson", ctx)
        self.assertNotIn("PERSONAL lesson", ctx)


if __name__ == "__main__":
    unittest.main()
