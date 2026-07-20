"""Tests for nervepack_engine.hooks.skill_trigger_recall — the Python port of
skill-trigger-recall.sh. Ports all 4 scenarios from
engine/setup/tests/skills/test_skill_trigger_recall.sh plus one new case
(test_5) covering the toggle-off path, which the bash test never exercised."""
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is engine/setup/tests/nervepack_engine — two levels up is engine/setup,
# three levels up is engine/
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestSkillTriggerRecall(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("skills|shared|runtime|on|\n")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local"),
            "NP_SKILL_TRIGGER_STATE": os.path.join(self.tmp, "state"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, sid, prompt):
        from nervepack_engine.hooks import skill_trigger_recall
        return skill_trigger_recall.run(json.dumps({"session_id": sid, "prompt": prompt}))

    def test_1_matching_refactor_skill_injects_reminder(self):
        out = self._run("s1", "I want to refactor this skill to be leaner")
        self.assertTrue(out)
        self.assertIn("disciplined skill-authoring process",
                       json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_2_once_per_session_second_call_silent(self):
        self._run("s1", "I want to refactor this skill to be leaner")
        out2 = self._run("s1", "refactor the skill again")
        self.assertEqual(out2, "")

    def test_3_skill_md_reference_new_session_injects(self):
        out3 = self._run("s2", "update SKILL.md for the new feature")
        self.assertIn("Skill-writing trigger", json.loads(out3)["hookSpecificOutput"]["additionalContext"])

    def test_4_unrelated_prompt_silent(self):
        out4 = self._run("s3", "fix the authentication bug in the API")
        self.assertEqual(out4, "")

    def test_5_toggle_off_silent_even_on_match(self):
        with open(os.path.join(self.tmp, "local"), "w") as fh:
            fh.write("skills.trigger_recall=off\n")
        out = self._run("s4", "refactor this skill please")
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
