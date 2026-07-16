"""Tests for nervepack_engine.hooks.session_directive -- the Python port of
nervepack-session-directive.sh. Ports all 7 scenarios spread across the bash
suite's 4 core-script test files (test_directive_stable.sh, test_directive_
failure.sh, test_directive_composed_stable.sh, test_directive_team_routing.sh)
plus one new case (test_8) covering the toggle-off path, which no bash test
ever exercised. The NERVEPACK_AGENT re-entry guard scenario from
test_directive_failure.sh is intentionally NOT re-tested here: it is already
covered generically for every hook by test_cli.py's
test_nervepack_agent_guard_skips_dispatch."""
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is engine/setup/tests/nervepack_engine -- two levels up is engine/setup,
# three levels up is engine/
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestSessionDirective(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("directive|shared|runtime|on|\n")
        self.toggles_local = os.path.join(self.tmp, "local")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": self.toggles_local,
        }, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        for _k in ("NP_CONTENT_DIR", "NP_TEAM_DIR"):
            os.environ.pop(_k, None)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self):
        from nervepack_engine.hooks import session_directive
        return session_directive.run("")

    def test_1_byte_stable_and_nonempty(self):
        a = self._run()
        b = self._run()
        self.assertEqual(a, b)
        self.assertTrue(a)
        parsed = json.loads(a)
        self.assertEqual(parsed["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", parsed["hookSpecificOutput"])

    def test_2_missing_directive_md_fails_open(self):
        from nervepack_engine.hooks import session_directive
        with mock.patch.object(session_directive, "_DIRECTIVE_PATH",
                                os.path.join(self.tmp, "does-not-exist.md")):
            out = session_directive.run("")
        self.assertEqual(out, "")

    def test_3_fragment_absent_engine_only_stable_no_hardcoded_row(self):
        content_dir = os.path.join(self.tmp, "content-none")
        os.makedirs(content_dir, exist_ok=True)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": content_dir}):
            a = self._run()
            b = self._run()
        self.assertEqual(a, b)
        ctx = json.loads(a)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("np-kb-chrome", ctx)

    def test_4_fragment_present_appended_and_stable(self):
        content_dir = os.path.join(self.tmp, "content")
        os.makedirs(content_dir, exist_ok=True)
        with open(os.path.join(content_dir, "directive-routing.md"), "w") as fh:
            fh.write("## Personal routing\n| Trigger | Skill |\n")
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": content_dir}):
            a = self._run()
            b = self._run()
        self.assertEqual(a, b)
        ctx = json.loads(a)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Personal routing", ctx)

    def test_5_team_on_both_fragments_team_before_personal(self):
        personal = os.path.join(self.tmp, "personal"); os.makedirs(personal, exist_ok=True)
        team = os.path.join(self.tmp, "team"); os.makedirs(team, exist_ok=True)
        with open(os.path.join(personal, "directive-routing.md"), "w") as fh:
            fh.write("## Personal routing\n| Ptrig | Pskill |\n")
        with open(os.path.join(team, "directive-routing.md"), "w") as fh:
            fh.write("## Team routing\n| Ttrig | Tskill |\n")
        with open(self.toggles_local, "w") as fh:
            fh.write("team=on\n")
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": personal, "NP_TEAM_DIR": team}):
            a = self._run()
            b = self._run()
        self.assertEqual(a, b)
        ctx = json.loads(a)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Team routing", ctx)
        self.assertIn("Personal routing", ctx)
        self.assertLess(ctx.index("Team routing"), ctx.index("Personal routing"))

    def test_6_team_off_personal_only(self):
        personal = os.path.join(self.tmp, "personal2"); os.makedirs(personal, exist_ok=True)
        team = os.path.join(self.tmp, "team2"); os.makedirs(team, exist_ok=True)
        with open(os.path.join(personal, "directive-routing.md"), "w") as fh:
            fh.write("## Personal routing\n| Ptrig | Pskill |\n")
        with open(os.path.join(team, "directive-routing.md"), "w") as fh:
            fh.write("## Team routing\n| Ttrig | Tskill |\n")
        with open(self.toggles_local, "w") as fh:
            fh.write("team=off\n")
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": personal, "NP_TEAM_DIR": team}):
            out = self._run()
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Personal routing", ctx)
        self.assertNotIn("Team routing", ctx)

    def test_7_team_on_no_fragments_failopen_validjson(self):
        personal = os.path.join(self.tmp, "personal3"); os.makedirs(personal, exist_ok=True)
        team = os.path.join(self.tmp, "team3"); os.makedirs(team, exist_ok=True)
        with open(self.toggles_local, "w") as fh:
            fh.write("team=on\n")
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": personal, "NP_TEAM_DIR": team}):
            out = self._run()
        parsed = json.loads(out)  # must not raise
        ctx = parsed["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Team routing", ctx)
        self.assertNotIn("Personal routing", ctx)

    def test_8_toggle_off_silent(self):
        with open(self.toggles_conf, "w") as fh:
            fh.write("directive|shared|runtime|off|\n")
        out = self._run()
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
