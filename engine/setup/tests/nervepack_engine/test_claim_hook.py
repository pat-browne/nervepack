"""Tests for hooks/claim_hook.py: prompt surfacing, marker dedupe, end release."""
import json
import os
import subprocess
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

from nervepack_engine.hooks import claim_hook  # noqa: E402
import np_claims  # noqa: E402


def _git(cwd, *args):
    subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                   check=True, capture_output=True)


class ClaimHookCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.local = os.path.join(self.tmp, "toggles.local")
        env = mock.patch.dict(os.environ, {
            "HOME": self.tmp, "XDG_CACHE_HOME": os.path.join(self.tmp, "cache"),
            "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
            "NP_TOGGLES_LOCAL": self.local})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("NERVEPACK_AGENT", None)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "commit", "-q", "--allow-empty", "-m", "init")
        self.wt = os.path.join(self.tmp, "wt")
        _git(self.repo, "worktree", "add", "-q", "-b", "other", self.wt)

    def payload(self, sid, cwd):
        return json.dumps({"session_id": sid, "cwd": cwd})

    def claims(self):
        d = os.path.join(self.repo, ".git", "nervepack", "claims")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_alone_then_second_session_then_marker(self):
        self.assertEqual(claim_hook.run(self.payload("aaaa1111", self.repo)), "")
        out = claim_hook.run(self.payload("bbbb2222", self.wt))
        ctx = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "UserPromptSubmit")
        self.assertIn("You are 2 in", ctx["additionalContext"])
        self.assertEqual(claim_hook.run(self.payload("bbbb2222", self.wt)), "")

    def test_leader_sees_first_in_once_and_marker_exists(self):
        claim_hook.run(self.payload("bbbb2222", self.wt))
        np_claims.write("aaaa1111", self.repo, force=True)
        self.edit_started("aaaa1111", 1)
        out = claim_hook.run(self.payload("aaaa1111", self.repo))
        self.assertIn("You are first in", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(claim_hook.run(self.payload("aaaa1111", self.repo)), "")
        markers = os.listdir(os.path.join(self.tmp, "cache", "nervepack", "claims-state"))
        self.assertEqual(len([m for m in markers if "aaaa1111" in m]), 1)

    def edit_started(self, sid, started):
        path = os.path.join(self.repo, ".git", "nervepack", "claims", sid + ".json")
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        rec["started"] = started
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh)

    def test_end_releases_and_new_set_resurfaces(self):
        claim_hook.run(self.payload("aaaa1111", self.repo))
        self.assertIn("You are 2 in", claim_hook.run(self.payload("bbbb2222", self.wt)))
        self.assertEqual(claim_hook.run(self.payload("aaaa1111", self.repo), "end"), "")
        self.assertEqual(self.claims(), ["bbbb2222.json"])
        self.assertEqual(claim_hook.run(self.payload("bbbb2222", self.wt)), "")
        claim_hook.run(self.payload("cccc3333", self.repo))
        self.assertIn("cccc3333", claim_hook.run(self.payload("bbbb2222", self.wt)))

    def test_toggle_off_writes_nothing(self):
        with open(self.local, "w", encoding="utf-8") as fh:
            fh.write("claims=off\n")
        self.assertEqual(claim_hook.run(self.payload("aaaa1111", self.repo)), "")
        self.assertEqual(self.claims(), [])

    def test_missing_session_id(self):
        self.assertEqual(claim_hook.run(json.dumps({"cwd": self.repo})), "")
        self.assertEqual(self.claims(), [])

    def test_non_git_cwd(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.assertEqual(claim_hook.run(self.payload("aaaa1111", plain)), "")

    def test_bad_json_and_agent_guard(self):
        self.assertEqual(claim_hook.run("not json"), "")
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            self.assertEqual(claim_hook.run(self.payload("aaaa1111", self.repo)), "")
        self.assertEqual(self.claims(), [])


if __name__ == "__main__":
    unittest.main()
