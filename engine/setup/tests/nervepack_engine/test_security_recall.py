"""Tests for nervepack_engine.hooks.security_recall — UserPromptSubmit hook
that injects a security-review reminder on security/vulnerability keywords."""
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP, os.path.join(_ENGINE_DIR, "nervepack_engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TestSecurityRecall(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        with open(self.toggles_conf, "w") as fh:
            fh.write("skills|shared|runtime|on|\n")
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local"),
            "NP_SECURITY_RECALL_STATE": os.path.join(self.tmp, "state"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, sid, prompt):
        from nervepack_engine.hooks import security_recall
        return security_recall.run(json.dumps({"session_id": sid, "prompt": prompt}))

    def test_1_security_keyword_injects_reminder(self):
        out = self._run("s1", "review the security of this authentication flow")
        self.assertTrue(out)
        data = json.loads(out)
        self.assertIn("security-review", data["hookSpecificOutput"]["additionalContext"])

    def test_2_vulnerability_keyword_injects_reminder(self):
        out = self._run("s2", "check for any vulnerability in the login handler")
        self.assertTrue(out)
        self.assertIn("Security-review trigger",
                      json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_3_once_per_session_second_call_silent(self):
        self._run("s3", "fix the security bug")
        out2 = self._run("s3", "another security concern here")
        self.assertEqual(out2, "")

    def test_4_unrelated_prompt_silent(self):
        out = self._run("s4", "refactor the database layer for performance")
        self.assertEqual(out, "")

    def test_5_toggle_off_silent_even_on_match(self):
        with open(os.path.join(self.tmp, "local"), "w") as fh:
            fh.write("skills.security_recall=off\n")
        out = self._run("s5", "security review this endpoint")
        self.assertEqual(out, "")

    def test_6_exploit_keyword_injects_reminder(self):
        out = self._run("s6", "could this be exploited via path traversal?")
        self.assertTrue(out)

    def test_7_different_sessions_fire_independently(self):
        self._run("s7a", "security audit needed")
        out2 = self._run("s7b", "check vulnerability in the api")
        self.assertTrue(out2)


if __name__ == "__main__":
    unittest.main()
