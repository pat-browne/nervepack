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
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
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
        with open(os.path.join(self.lessons, name), "w", encoding="utf-8") as fh:
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

    # --- issue #152: arming is tool_name_match-VALUE-agnostic -- a lesson
    # targeting an MCP tool-name regex (not just a literal like "Read") still
    # arms lesson_guard.py's Phase 2 the same way, since the arming check
    # (_TOOL_NAME_MATCH_RE) only looks for the frontmatter KEY, never its value.
    def test_10_arms_regardless_of_tool_name_match_being_an_mcp_regex(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| concise-output |  | warn | concise, pr, write |\n")
        self._write("concise-output.md",
            "---\nname: concise-output\nprovenance: failure\n"
            "enforce:\n  tool_match: \"\"\n"
            "  tool_name_match: \"^(Edit|Write|mcp__.*__(repo_create_pull_request|repo_reply_to_comment))$\"\n"
            "  gate: warn\n---\n"
            "**Do:** run np-flow-concise-output before the write completes.\n")
        self._run("s11", "drafting a concise pr description")
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp, "state", "s11-concise-output-gate-armed")))

    # --- paired-rule format (spec 0093) ---
    def test_11_paired_success_rule_injected_without_backlink(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| bulk-rename |  |  | rename |\n")
        self._write("bulk-rename.md",
            "---\nname: bulk-rename\nprovenance: success\n---\n"
            "## Ship the rename safely\n"
            "- DO run the guarded rename in one pass — **when** renaming across the repo — "
            "**why** a bare replace hits unrelated words. [[episodic/bulk-rename]]\n")
        out = self._run("s12", "need to do a bulk rename")
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Ship the rename safely (worked before):", ctx)
        self.assertIn("- DO run the guarded rename in one pass", ctx)
        self.assertNotIn("[[", ctx)
        self.assertNotIn("episodic/bulk-rename", ctx)
        # Paired rules are self-framing: no legacy "approaches that worked" preamble.
        self.assertNotIn("Approaches that worked before", ctx)

    def test_12_empty_failure_body_injects_no_topic_tag(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| empty-lesson |  |  | deploy |\n")
        self._write("empty-lesson.md",
            "---\nname: empty-lesson\nprovenance: failure\n---\n")
        out = self._run("s13", "about to deploy")
        self.assertEqual(out, "")

    def test_13_legacy_failure_stacked_with_paired_success(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| mixed |  |  | lockfile |\n")
        self._write("mixed.md",
            "---\nname: mixed\nprovenance: failure\n---\n"
            "**Do:** pin the lockfile first.\n"
            "---\nname: mixed\nprovenance: success\n---\n"
            "## Ship the lockfile bump\n"
            "- DO run the audit before merging — **when** bumping deps — "
            "**why** it catches drift early. [[episodic/mixed]]\n")
        out = self._run("s14", "bump the lockfile")
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("past failure patterns apply", ctx)
        self.assertIn("[mixed] **Do:** pin the lockfile first.", ctx)
        self.assertIn("Ship the lockfile bump (worked before):", ctx)
        self.assertIn("- DO run the audit before merging", ctx)
        self.assertNotIn("[[", ctx)

    def test_14_paired_failure_with_tool_name_match_arms_gate(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| guarded-write |  | ask | edit, lockfile |\n")
        self._write("guarded-write.md",
            "---\nname: guarded-write\nprovenance: failure\n"
            "enforce:\n  tool_match: \"\"\n  tool_name_match: \"Edit\"\n  gate: ask\n---\n"
            "## Editing generated files\n"
            "- DON'T edit the lockfile by hand → DO regenerate it — **when** touching deps — "
            "**why** hand edits drift from the resolver. [[episodic/guarded-write]]\n")
        out = self._run("s15", "edit the lockfile now")
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("DO regenerate it", ctx)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp, "state", "s15-guarded-write-gate-armed")))


    # --- recall gate: whole-word match, ranked, capped ---
    def _lesson(self, topic):
        self._write(topic + ".md", "---\nprovenance: failure\n---\n**Do:** %s-body\n" % topic)

    def test_recall_gate_substring_does_not_match(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| ci-timeouts |  |  | ci |\n")
        self._lesson("ci-timeouts")
        self.assertEqual(self._run("g1", "record the decision in the spec"), "")
        self.assertIn("ci-timeouts-body", self._run("g2", "the ci job hung"))

    def test_recall_gate_hyphenated_trigger_matches_spaced_prompt(self):
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            "| gha |  |  | github-actions |\n")
        self._lesson("gha")
        self.assertIn("gha-body", self._run("g3", "fix the github actions workflow"))

    def test_recall_gate_caps_at_top_n_preferring_more_and_rarer_hits(self):
        rows = "".join("| t%d |  |  | merge |\n" % n for n in range(5))
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n"
            + rows + "| squash |  |  | merge, squash |\n")
        for n in range(5):
            self._lesson("t%d" % n)
        self._lesson("squash")
        ctx = json.loads(self._run("g4", "squash merge this"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("squash-body", ctx)
        self.assertEqual(sum(("t%d-body" % n) in ctx for n in range(5)), 2)


    def test_recall_gate_arms_tool_gate_beyond_the_cap(self):
        rows = "".join("| t%d |  |  | merge |\n" % n for n in range(4))
        self._write("INDEX.md",
            "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n" + rows)
        for n in range(4):
            self._lesson("t%d" % n)
        self._write("t3.md", "---\nprovenance: failure\nenforce:\n  tool_name_match: mcp__x\n---\n**Do:** t3-body\n")
        self._run("g5", "merge it")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "state", "g5-t3-gate-armed")))

    def test_recall_gate_arms_every_gated_lesson_past_the_cap(self):
        self._index("".join("| t%d |  |  | merge |\n" % n for n in range(5)))
        for n in range(3):
            self._lesson("t%d" % n)
        for n in (3, 4):
            self._write("t%d.md" % n, "---\nprovenance: failure\nenforce:\n  tool_name_match: mcp__x\n---\n**Do:** b\n")
        self._run("g17", "merge it")
        for n in (3, 4):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "state", "g17-t%d-gate-armed" % n)))

    def test_recall_gate_below_min_hits_is_not_armed(self):
        self._index("| gated |  |  | merge |\n")
        self._write("gated.md", "---\nprovenance: failure\nenforce:\n  tool_name_match: mcp__x\n---\n**Do:** b\n")
        self._param("lessons.recall_min_hits=2")
        self.assertEqual(self._run("g18", "merge it"), "")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state", "g18-gated-gate-armed")))

    def test_recall_gate_more_hits_beat_a_rarer_trigger(self):
        # "deploy" and "merge" are shared, "rebase" is unique. Two common hits outrank one rare hit.
        # Rarity: "two" scores 2 x 1/4 = 0.5, "rare" scores 1.0, so hits must decide.
        self._index("| two |  |  | deploy, merge |\n"
                    + "".join("| f%d |  |  | deploy, merge |\n" % n for n in range(3))
                    + "| rare |  |  | rebase |\n")
        for t in ("two", "f0", "f1", "f2", "rare"):
            self._lesson(t)
        self._param("lessons.recall_top=1")
        ctx = self._ctx("g19", "deploy, merge, rebase")
        self.assertIn("two-body", ctx)
        self.assertNotIn("rare-body", ctx)

    def test_recall_gate_bad_min_hits_falls_back_to_one(self):
        self._index("| one |  |  | deploy |\n")
        self._lesson("one")
        self._param("lessons.recall_min_hits=x")
        self.assertIn("one-body", self._ctx("g20", "deploy now"))


    def _index(self, rows):
        self._write("INDEX.md", "| topic | tool_match | gate | topic_triggers |\n|---|---|---|---|\n" + rows)

    def _ctx(self, sid, prompt):
        out = self._run(sid, prompt)
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def _param(self, line):
        with open(self.toggles_local, "a") as fh:
            fh.write(line + "\n")

    def test_recall_gate_rarer_trigger_breaks_a_hit_tie(self):
        # "merge" is shared by three topics, "rebase" by one. Each topic hits once,
        # so the rarer trigger wins even though it is last in the index.
        self._index("| common-a |  |  | merge |\n| common-b |  |  | merge |\n"
                    "| common-c |  |  | merge |\n| rare |  |  | rebase |\n")
        for t in ("common-a", "common-b", "common-c", "rare"):
            self._lesson(t)
        self._param("lessons.recall_top=1")
        ctx = self._ctx("g6", "merge and rebase")
        self.assertIn("rare-body", ctx)
        self.assertNotIn("common-a-body", ctx)

    def test_recall_gate_ties_keep_index_order(self):
        self._index("| first |  |  | deploy |\n| second |  |  | deploy |\n")
        self._lesson("first")
        self._lesson("second")
        self._param("lessons.recall_top=1")
        self.assertIn("first-body", self._ctx("g7", "deploy now"))

    def test_recall_gate_top_param_is_honored(self):
        self._index("".join("| t%d |  |  | deploy |\n" % n for n in range(6)))
        for n in range(6):
            self._lesson("t%d" % n)
        self._param("lessons.recall_top=5")
        ctx = self._ctx("g8", "deploy now")
        self.assertEqual(sum(("t%d-body" % n) in ctx for n in range(6)), 5)

    def test_recall_gate_min_hits_param_suppresses_weak_matches(self):
        self._index("| weak |  |  | deploy |\n| strong |  |  | deploy, rollback |\n")
        self._lesson("weak")
        self._lesson("strong")
        self._param("lessons.recall_min_hits=2")
        ctx = self._ctx("g9", "deploy then rollback")
        self.assertIn("strong-body", ctx)
        self.assertNotIn("weak-body", ctx)
        self.assertEqual(self._run("g10", "deploy only"), "")

    def test_recall_gate_bad_param_values_fall_back_to_defaults(self):
        self._index("".join("| t%d |  |  | deploy |\n" % n for n in range(4)))
        for n in range(4):
            self._lesson("t%d" % n)
        self._param("lessons.recall_top=lots")
        self._param("lessons.recall_min_hits=x")
        ctx = self._ctx("g11", "deploy now")
        self.assertEqual(sum(("t%d-body" % n) in ctx for n in range(4)), 3)

    def test_recall_gate_multiword_trigger_needs_the_phrase(self):
        self._index("| sq |  |  | squash merge |\n")
        self._lesson("sq")
        self.assertEqual(self._run("g12", "squash the commits, then merge"), "")
        self.assertIn("sq-body", self._ctx("g13", "do a squash merge"))

    def test_recall_gate_ignores_case_and_punctuation(self):
        self._index("| ci-t |  |  | ci |\n")
        self._lesson("ci-t")
        self.assertIn("ci-t-body", self._ctx("g14", "Why is CI, again, red?"))

    def test_recall_gate_blank_triggers_never_match(self):
        self._index("| blank |  |  |  |\n| commas |  |  | , , |\n")
        self._lesson("blank")
        self._lesson("commas")
        self.assertEqual(self._run("g15", "anything at all"), "")

    def test_recall_gate_success_lesson_beyond_cap_is_neither_injected_nor_armed(self):
        self._index("".join("| t%d |  |  | deploy |\n" % n for n in range(4)))
        for n in range(3):
            self._lesson("t%d" % n)
        self._write("t3.md", "---\nprovenance: success\nenforce:\n  tool_name_match: mcp__x\n---\n**Do:** t3-body\n")
        ctx = self._ctx("g16", "deploy now")
        self.assertNotIn("t3-body", ctx)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state", "g16-t3-gate-armed")))


if __name__ == "__main__":
    unittest.main()
