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
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = os.path.join(self.tmp, "fake-env-home")
        self._pw = mock.patch(
            "np_speed._home_dir", return_value=os.path.join(self.tmp, "home"))
        self._pw.start()
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, ".git"))
        os.makedirs(os.path.join(self.repo, "change-specs"))
        with open(os.path.join(self.repo, ".git", "HEAD"), "w") as fh:
            fh.write("ref: refs/heads/feat-x\n")
        with open(os.path.join(self.repo, "change-specs", "feat-x.md"), "w") as fh:
            fh.write(SPEC)

    def tearDown(self):
        self._pw.stop()
        if self._home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._home
        for var in ("NP_SPEC_REVIEW_LOG", "NP_DRIFT_GUARD_LOG",
                    "NP_SPEC_REVIEW_DIR", "NP_SPEED_DIR"):
            os.environ.pop(var, None)

    def _transcript(self, sid=SID, root=None, create=True):
        root = root or os.path.join(self.tmp, "home", ".claude", "projects", "p")
        path = os.path.join(root, sid + ".jsonl")
        if create:
            os.makedirs(root, exist_ok=True)
            open(path, "w").close()
        return path

    def _symlink(self, target, link):
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")

    def _ups(self, **kw):
        p = {"session_id": SID, "hook_event_name": "UserPromptSubmit",
             "prompt": "/np-speed", "transcript_path": self._transcript()}
        p.update(kw)
        return {k: v for k, v in p.items() if v is not None}

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
        np_speed.mark("root-sid")
        cwd = "/work/proj/.claude/worktrees/agent-abc"
        out = self._call(spec_review, "engine/a.py", session_id="child", cwd=cwd)
        self.assertEqual(self._decision(out), "ask")


class TestTtl(_Base):
    def _age(self, hours):
        path = os.path.join(self.tmp, "speed", SID)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"ts": __import__("time").time() - hours * 3600, "cwd": ""}, fh)

    def _with_ttl(self, ttl):
        return mock.patch("np_toggle.param",
                          side_effect=lambda k, d=None: ttl if k == "gates.speed_silent_ttl_h" else d)

    def test_fresh_marker_silences(self):
        self._age(11)
        self.assertEqual(self._call(spec_review, "engine/a.py"), "")

    def test_old_marker_asks(self):
        self._age(13)
        self.assertEqual(self._decision(self._call(spec_review, "engine/a.py")), "ask")

    def test_ttl_param_widens(self):
        self._age(13)
        with self._with_ttl("24"):
            self.assertEqual(self._call(spec_review, "engine/a.py"), "")

    def test_bad_ttl_falls_back_to_12(self):
        self._age(13)
        with self._with_ttl("junk"):
            self.assertEqual(self._decision(self._call(spec_review, "engine/a.py")), "ask")


class TestPathAndFailure(_Base):
    def test_sanitised_ids_do_not_collide(self):
        ids = [".A.B", "A.B", "a/b", "a_b", "a\\b", "..", "x"]
        paths = {np_speed._path(i) for i in ids}
        self.assertEqual(len(paths), len(ids))

    def test_one_helper_for_both_modules(self):
        for sid in ("../x", "a/b", ".A", "ok-1"):
            self.assertEqual(os.path.basename(np_speed._path(sid)), np_speed.safe_id(sid))
            self.assertEqual(spec_review._safe_sid(sid), np_speed.safe_id(sid))

    def test_traversal_sid_stays_in_receipt_dir_and_log_is_one_line(self):
        seen = os.environ["NP_SPEC_REVIEW_DIR"]
        got = spec_review._receipt_path("../x")
        self.assertEqual(os.path.dirname(got), seen)
        spec_review.log_verdict("T", "../x\nspec-review FORGED sid=y", "d")
        text = self._log("sr.log")
        self.assertEqual(len(text.splitlines()), 1)
        self.assertNotIn("../", text)

    def test_plain_uuid_keeps_its_name(self):
        self.assertEqual(os.path.basename(np_speed._path("abc-123")), "abc-123")

    def test_marker_holds_no_cwd(self):
        np_speed.mark(SID)
        with open(os.path.join(self.tmp, "speed", SID)) as fh:
            self.assertEqual(set(json.load(fh)), {"ts"})

    def test_write_failure_is_logged_to_spec_review_log(self):
        blocker = os.path.join(self.tmp, "blocker")
        open(blocker, "w").close()
        os.environ["NP_SPEED_DIR"] = os.path.join(blocker, "sub")
        from hooks import speed_mark
        speed_mark.run(json.dumps(self._ups()))
        self.assertIn("MARKFAIL", self._log("sr.log"))


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
        self._hook(self._ups(prompt="/np-flow-speed fix it"))
        self.assertTrue(self._marked())

    def test_short_prompt_slash_marks(self):
        self._hook(self._ups(prompt="  /np-speed"))
        self.assertTrue(self._marked())

    def test_wrong_event_name_does_not_mark(self):
        for ev in ("PreToolUse", "SubagentStop", None):
            self._hook(self._ups(hook_event_name=ev))
            self.assertFalse(self._marked(), ev)

    def test_transcript_session_mismatch_does_not_mark(self):
        self._hook(self._ups(transcript_path=self._transcript("other-sid")))
        self.assertFalse(self._marked())

    def test_missing_transcript_path_does_not_mark(self):
        self._hook(self._ups(transcript_path=None))
        self.assertFalse(self._marked())

    def test_transcript_file_must_exist(self):
        missing = self._transcript(root=os.path.join(self.tmp, "home", ".claude", "projects", "gone"), create=False)
        self._hook(self._ups(transcript_path=missing))
        self.assertFalse(self._marked())

    def test_transcript_outside_projects_does_not_mark(self):
        outside = self._transcript(root=os.path.join(self.tmp, "elsewhere"))
        self._hook(self._ups(transcript_path=outside))
        self.assertFalse(self._marked())

    def test_symlink_out_of_projects_does_not_mark(self):
        real = self._transcript(root=os.path.join(self.tmp, "elsewhere"))
        root = os.path.join(self.tmp, "home", ".claude", "projects", "q")
        os.makedirs(root)
        link = os.path.join(root, SID + ".jsonl")
        self._symlink(real, link)
        self._hook(self._ups(transcript_path=link))
        self.assertFalse(self._marked())

    def test_session_comes_from_the_resolved_path(self):
        other = self._transcript("other-sid")
        root = os.path.join(self.tmp, "home", ".claude", "projects", "q")
        os.makedirs(root)
        link = os.path.join(root, SID + ".jsonl")
        self._symlink(other, link)
        self._hook(self._ups(transcript_path=link))
        self.assertFalse(self._marked())

    @unittest.skipIf(np_speed.pwd is None, "no passwd database on this platform")
    def test_home_comes_from_passwd_not_env(self):
        import pwd
        os.environ["HOME"] = os.path.join(self.tmp, "fake-env-home")
        self._pw.stop()
        try:
            self.assertEqual(np_speed._home_dir(), pwd.getpwuid(os.getuid()).pw_dir)
        finally:
            self._pw.start()

    def test_home_falls_back_to_expanduser_without_pwd(self):
        self._pw.stop()
        try:
            with mock.patch.object(np_speed, "pwd", None):
                self.assertEqual(np_speed._home_dir(), os.path.expanduser("~"))
        finally:
            self._pw.start()

    def test_empty_or_relative_home_does_not_mark(self):
        import np_host
        self.assertEqual(np_host.default_under("transcripts", ""), "")
        self.assertEqual(np_host.default_under("transcripts", "rel/home"), "")
        payload = self._ups()
        for home in ("", "rel/home"):
            self._pw.stop()
            self._pw = mock.patch("np_speed._home_dir", return_value=home)
            self._pw.start()
            self._hook(payload)
            self.assertFalse(self._marked(), repr(home))

    def test_missing_projects_root_does_not_mark(self):
        payload = self._ups()
        import shutil
        shutil.rmtree(os.path.join(self.tmp, "home", ".claude", "projects"))
        open(os.path.join(self.tmp, "home", ".claude", "t.jsonl"), "w").close()
        payload["transcript_path"] = os.path.join(self.tmp, "home", ".claude", "t.jsonl")
        self._hook(payload)
        self.assertFalse(self._marked())

    def test_prompt_mentioning_speed_does_not_mark(self):
        self._hook(self._ups(prompt="what is speed mode? /np-flow-speed"))
        self.assertFalse(self._marked())


if __name__ == "__main__":
    unittest.main()
