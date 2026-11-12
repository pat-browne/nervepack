# np-test: speed-silence | failure
"""Speed mode silences spec-review only; drift-guard and everything else stay."""
import json
import os
import sys
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

import np_speed  # noqa: E402
from hooks import drift_guard, spec_review  # noqa: E402

SPEC = ("---\nid: 1\nstatus: accepted\ndate: 2026-11-12\ntier: high\n"
        "blast_radius:\n  - engine/**\n---\n\n# spec\n")
SID = "parent-sid"


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        for var, name in (("NP_SPEC_REVIEW_LOG", "sr.log"),
                          ("NP_DRIFT_GUARD_LOG", "dg.log")):
            os.environ[var] = os.path.join(self.tmp, name)
        os.environ["NP_SPEC_REVIEW_DIR"] = os.path.join(self.tmp, "seen")
        os.environ["NP_SPEED_DIR"] = os.path.join(self.tmp, "speed")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.repo, "change-specs"))
        with open(os.path.join(self.repo, ".git", "HEAD"), "w") as fh:
            fh.write("ref: refs/heads/feat-x\n")
        with open(os.path.join(self.repo, "change-specs", "feat-x.md"), "w") as fh:
            fh.write(SPEC)

    def tearDown(self):
        for var in ("NP_SPEC_REVIEW_LOG", "NP_DRIFT_GUARD_LOG",
                    "NP_SPEC_REVIEW_DIR", "NP_SPEED_DIR"):
            os.environ.pop(var, None)

    def _payload(self, rel, **extra):
        p = {"session_id": SID, "tool_name": "Edit",
             "tool_input": {"file_path": os.path.join(self.repo, rel)}}
        p.update(extra)
        return json.dumps(p)

    def _call(self, hook, rel, speed_silent=True, **extra):
        states = {"gates.speed_silent": speed_silent}
        with mock.patch("np_toggle.enabled",
                        side_effect=lambda f: states.get(f, True)):
            return hook.run(self._payload(rel, **extra))

    def _decision(self, out):
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else ""

    def _log(self, name):
        path = os.path.join(self.tmp, name)
        return open(path).read() if os.path.isfile(path) else ""


class TestUnmarked(_Base):
    def test_spec_review_still_asks(self):
        self.assertEqual(self._decision(self._call(spec_review, "engine/a.py")), "ask")

    def test_drift_guard_still_denies(self):
        self.assertEqual(self._decision(self._call(drift_guard, "docs/a.md")), "deny")


class TestMarked(_Base):
    def setUp(self):
        super().setUp()
        np_speed.mark(SID)

    def test_spec_review_silent_and_logged(self):
        self.assertEqual(self._call(spec_review, "engine/a.py"), "")
        self.assertIn("speed mode", self._log("sr.log"))

    def test_drift_guard_still_denies_in_marked_session(self):
        self.assertEqual(self._decision(self._call(drift_guard, "docs/a.md")), "deny")

    def test_toggle_off_asks_again(self):
        self.assertEqual(
            self._decision(self._call(spec_review, "engine/a.py", speed_silent=False)), "ask")

    def test_other_session_not_silenced(self):
        out = self._call(spec_review, "engine/a.py", session_id="other")
        self.assertEqual(self._decision(out), "ask")

    def test_subagent_with_parent_session_id(self):
        out = self._call(spec_review, "engine/a.py", agent_id="a1")
        self.assertEqual(out, "")

    def test_subagent_with_own_id_via_transcript_path(self):
        tp = "/home/x/.claude/projects/p/%s/subagents/agent-a1.jsonl" % SID
        out = self._call(spec_review, "engine/a.py", session_id="child", transcript_path=tp)
        self.assertEqual(out, "")

    def test_agent_worktree_cwd_alone_is_not_silenced(self):
        np_speed.mark("root-sid", cwd="/work/proj")
        cwd = "/work/proj/.claude/worktrees/agent-abc"
        out = self._call(spec_review, "engine/a.py", session_id="child", cwd=cwd)
        self.assertEqual(self._decision(out), "ask")


class TestMarking(_Base):
    def _hook(self, payload):
        import json as _j
        from hooks import speed_mark
        return speed_mark.run(_j.dumps(payload))

    def _marked(self):
        return os.path.isfile(os.path.join(self.tmp, "speed", SID))

    def test_skill_call_writes_no_marker(self):
        for name in ("np-flow-speed", "nervepack:np-flow-speed", "np-speed"):
            self._hook({"session_id": SID, "tool_name": "Skill",
                        "tool_input": {"skill": name}})
            self.assertFalse(self._marked(), name)

    def test_prompt_slash_marks(self):
        self._hook({"session_id": SID, "prompt": "/np-flow-speed fix it"})
        self.assertTrue(self._marked())

    def test_short_prompt_slash_marks(self):
        self._hook({"session_id": SID, "prompt": "  /np-speed"})
        self.assertTrue(self._marked())

    def test_prompt_mentioning_speed_does_not_mark(self):
        self._hook({"session_id": SID, "prompt": "what is speed mode? /np-flow-speed"})
        self.assertFalse(self._marked())


if __name__ == "__main__":
    unittest.main()
