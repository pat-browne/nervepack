"""Tests for nervepack_engine.hooks.episodic_recall — the Python port of
episodic-recall.sh. Ports all scenarios from the two bash hook-behavior tests
being retired alongside the bash original:

  - engine/setup/tests/episodic/test_episodic_recall_layers.sh (3 scenarios:
    override, concatenate, no-team)
  - engine/setup/tests/episodic/test_recall.sh (3 scenarios: first-prompt
    inject, cap-then-silent after EPISODIC_RECALL_MAX prompts, non-matching
    prompt silent)

plus 2 further cases not covered by either bash test (no INDEX.md at all;
same behavior confirmed via a dedicated max-prompts-cap unit test rather than
relying on the bash test's specific counts). Uses np_content.merge_roots()/
merge_mode() and np_episodic_match.match() in-process — never shells to
np-layer-lib.sh or episodic-match.sh.
"""
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is engine/setup/tests/nervepack_engine — two levels up is engine/setup
# (needed so episodic_recall.py's own `import np_content`/`np_toggle`/
# `np_episodic_match` resolve when this test imports it directly, bypassing
# cli.py's own sys.path fixup), three levels up is engine/ (needed for
# `import nervepack_engine`).
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _mk_layer(root, marker_text):
    d = os.path.join(root, "memory", "episodic")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "INDEX.md"), "w") as fh:
        fh.write("| topic | last_updated | keywords | lines |\n|---|---|---|---|\n"
                  "| onboarding | 2026-06-01 | onboarding | 5 |\n")
    with open(os.path.join(d, "onboarding.md"), "w") as fh:
        fh.write("---\nname: onboarding\n---\n%s theme body\n" % marker_text)


class TestEpisodicRecall(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.personal = os.path.join(self.tmp, "personal")
        self.team = os.path.join(self.tmp, "team")
        os.makedirs(self.personal, exist_ok=True)
        os.makedirs(self.team, exist_ok=True)
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("memory|shared|runtime|on|\nteam|shared|runtime|on|\n")
        self.toggles_local = os.path.join(self.tmp, "local")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": self.toggles_local,
            "NP_CONTENT_DIR": self.personal,
            "NP_TEAM_DIR": self.team,
            "EPISODIC_STATE_DIR": os.path.join(self.tmp, "state"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, sid="s1", prompt="about onboarding"):
        from nervepack_engine.hooks import episodic_recall
        return episodic_recall.run(json.dumps({"session_id": sid, "prompt": prompt}))

    def test_1_override_mode_team_wins_personal_suppressed(self):
        _mk_layer(self.personal, "PERSONAL")
        _mk_layer(self.team, "TEAM")
        with open(self.toggles_local, "w") as fh:
            fh.write("team.merge=override\n")
        out = self._run()
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("TEAM theme", ctx)
        self.assertNotIn("PERSONAL theme", ctx)

    def test_2_concatenate_mode_both_present(self):
        _mk_layer(self.personal, "PERSONAL")
        _mk_layer(self.team, "TEAM")
        with open(self.toggles_local, "w") as fh:
            fh.write("team.merge=concatenate\n")
        out = self._run()
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("TEAM theme", ctx)
        self.assertIn("PERSONAL theme", ctx)

    def test_3_no_team_configured_personal_only(self):
        _mk_layer(self.personal, "PERSONAL")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NP_TEAM_DIR", None)
            out = self._run()
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("PERSONAL theme", ctx)

    def test_4_fires_at_most_max_prompts_times_per_session(self):
        _mk_layer(self.personal, "PERSONAL")
        with mock.patch.dict(os.environ, {"EPISODIC_RECALL_MAX": "2"}):
            os.environ.pop("NP_TEAM_DIR", None)
            out1 = self._run(sid="s9")
            out2 = self._run(sid="s9")
            out3 = self._run(sid="s9")
        self.assertTrue(out1)
        self.assertTrue(out2)
        self.assertEqual(out3, "")   # 3rd call this session exceeds EPISODIC_RECALL_MAX=2

    def test_5_no_index_md_anywhere_silent(self):
        # personal/team dirs exist but have no memory/episodic/INDEX.md at all
        out = self._run()
        self.assertEqual(out, "")

    def test_6_non_matching_prompt_is_silent(self):
        # Ports test_recall.sh's third scenario: an INDEX.md exists and has a
        # real topic, but the prompt shares no keywords with any topic row, so
        # np_episodic_match.match() returns [] and the hook must stay silent
        # rather than emit an empty/garbage additionalContext.
        _mk_layer(self.personal, "PERSONAL")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NP_TEAM_DIR", None)
            out = self._run(sid="s-nomatch", prompt="weather forecast")
        self.assertEqual(out, "")

    def test_7_first_prompt_injects_matching_theme(self):
        # Ports test_recall.sh's first scenario explicitly (distinct from the
        # layer-merge tests above): a single-layer INDEX.md, a prompt matching
        # its keywords, first call this session -> theme injected.
        _mk_layer(self.personal, "PERSONAL")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NP_TEAM_DIR", None)
            out = self._run(sid="s-first", prompt="about onboarding")
        self.assertTrue(out)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("PERSONAL theme", ctx)

    def test_8_pii_filter_invokes_injected_filter_fn(self):
        _mk_layer(self.personal, "PERSONAL")
        with open(self.toggles_conf, "w") as fh:
            fh.write("memory|shared|runtime|on|\nteam|shared|runtime|on|\npii_filter|shared|runtime|on|\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NP_TEAM_DIR", None)
            from nervepack_engine.hooks import episodic_recall
            calls = []

            def fake_filter(text):
                calls.append(text)
                return "REDACTED"

            out = episodic_recall.run(
                json.dumps({"session_id": "s-pii", "prompt": "about onboarding"}),
                pii_filter_fn=fake_filter)
        self.assertTrue(calls)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(ctx, "REDACTED")


if __name__ == "__main__":
    unittest.main()
