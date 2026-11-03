"""Tests for nervepack_engine.hooks.post_ship_capture: the PostToolUse Bash
hook that prompts np-core-capture-learning after a merge or deploy.
"""
import json
import os
import shutil
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

from nervepack_engine.hooks import post_ship_capture as psc  # noqa: E402


class TestPostShipCapture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.conf = os.path.join(self.tmp, "toggles.conf")
        self._write_conf("on")
        env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
            "NP_TOGGLES_CONTENT": os.path.join(self.tmp, "content-none"),
            "NP_SIGNAL_DIR": os.path.join(self.tmp, "signals"),
        }, clear=False)
        env.start()
        self.addCleanup(env.stop)

    def _write_conf(self, state):
        with open(self.conf, "w") as fh:
            fh.write("post_ship|shared|runtime|%s|\n" % state)

    def _run(self, command, response=None, tool="Bash"):
        payload = {"tool_name": tool, "session_id": "s1",
                   "tool_input": {"command": command},
                   "tool_response": response if response is not None else {"stdout": "ok", "stderr": ""}}
        return psc.run(json.dumps(payload))

    def _ctx(self, out):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def test_merge_hits(self):
        for cmd in ("gh pr merge 12 --squash --delete-branch",
                    "az repos pr update --id 9 --status completed",
                    "git push origin main",
                    "git push origin abc123:refs/heads/main"):
            with self.subTest(cmd=cmd):
                out = self._run(cmd)
                self.assertIn("np-core-capture-learning", self._ctx(out))
                self.assertIn("naming the KB location", self._ctx(out))
                self.assertNotIn("nothing new was learned", self._ctx(out))

    def test_deploy_hits(self):
        for cmd in ("databricks bundle deploy -t prod",
                    "terragrunt run-all apply",
                    "terraform apply -auto-approve",
                    "az deployment group create -g rg -f main.bicep",
                    "npm run deploy"):
            with self.subTest(cmd=cmd):
                self.assertEqual(json.loads(self._run(cmd))["hookSpecificOutput"]["hookEventName"], "PostToolUse")

    def test_failure_skipped(self):
        for resp in ({"stdout": "", "stderr": "", "exit_code": 1},
                     {"stdout": "", "stderr": "", "is_error": True},
                     {"stdout": "", "stderr": "", "interrupted": True},
                     {"stdout": "", "stderr": "error: rejected"},
                     "Error: Failed to apply"):
            with self.subTest(resp=resp):
                self.assertEqual(self._run("gh pr merge 3", resp), "")

    def test_unrelated_skipped(self):
        for cmd in ("git status", "git push origin feat/x", "gh pr view 3",
                    "terraform plan", "git push origin --delete main",
                    "databricks bundle deploy --dry-run"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self._run(cmd), "")

    def test_non_bash_skipped(self):
        self.assertEqual(self._run("gh pr merge 1", tool="Write"), "")

    def test_toggle_off(self):
        self._write_conf("off")
        self.assertEqual(self._run("gh pr merge 1"), "")

    def test_bad_payload(self):
        self.assertEqual(psc.run("not json"), "")


if __name__ == "__main__":
    unittest.main()
