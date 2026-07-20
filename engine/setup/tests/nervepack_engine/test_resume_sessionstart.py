"""Tests for nervepack_engine.hooks.resume_sessionstart — the Python port of
np-resume-sessionstart.sh. Ports both scenarios from
engine/setup/tests/resume/test_resume_sessionstart.sh: newest-settled-prior
selection (skipping current/agent-*/older-prior, proving newest-first not
oldest-first ordering) and no-settled-prior-session -> silent no-op."""
import json
import os
import sys
import time
import unittest
from unittest import mock

# _HERE is engine/setup/tests/nervepack_engine — two levels up is engine/setup
# (needed so resume_sessionstart.py's own `import np_toggle` resolves when this
# test imports it directly, bypassing cli.py's own sys.path fixup), three levels
# up is engine/ (needed for `import nervepack_engine`).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP = os.path.normpath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
for _p in (_ENGINE_DIR, _ENGINE_SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _init_repo(path):
    import subprocess
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "-C", path, "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "T"], check=True)
    with open(os.path.join(path, "README.md"), "w") as fh:
        fh.write("hello\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", "baseline"], check=True)


def _write_transcript(path, cwd, extra_line=None):
    # Compact (no spaces) to match real Claude Code transcript formatting —
    # the cwd-extraction regex in resume_sessionstart.py mirrors the bash
    # original's `grep -oE '"cwd":"[^"]*"'`, which has no tolerance for a
    # space after the colon.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "user", "cwd": cwd, "message": {"role": "user", "content": "hi"}},
                             separators=(",", ":")) + "\n")
        if extra_line:
            fh.write(json.dumps({"type": "user", "promptSource": "typed",
                                  "message": {"role": "user", "content": extra_line}},
                                 separators=(",", ":")) + "\n")


class TestResumeSessionstart(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.projects = os.path.join(self.tmp, "projects", "proj")
        os.makedirs(self.projects, exist_ok=True)
        self.pointer = os.path.join(self.tmp, "pointer.json")
        self.toggles_conf = os.path.join(self.tmp, "toggles.conf")
        open(self.toggles_conf, "w").close()
        self._env = mock.patch.dict(os.environ, {
            "NP_TOGGLES_CONF": self.toggles_conf,
            "NP_TOGGLES_LOCAL": os.path.join(self.tmp, "local-none"),
            "CLAUDE_PROJECTS_DIR": os.path.join(self.tmp, "projects"),
            "NP_RESUME_POINTER": self.pointer,
            "NP_RESUME_STAMP": os.path.join(self.tmp, "last-write"),
            "NP_RESUME_LOG": os.path.join(self.tmp, "resume.log"),
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import shutil
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _touch_ago(self, path, seconds):
        t = time.time() - seconds
        os.utime(path, (t, t))

    def _run(self, sid, cwd):
        from nervepack_engine.hooks import resume_sessionstart
        return resume_sessionstart.run(json.dumps({"session_id": sid, "cwd": cwd}))

    def test_1_picks_newest_settled_prior_not_current_agent_or_older(self):
        repo = os.path.join(self.tmp, "repo")
        older_repo = os.path.join(self.tmp, "older-repo")
        _init_repo(repo)
        _init_repo(older_repo)
        current_cwd = os.path.join(self.tmp, "currentcwd")
        os.makedirs(current_cwd, exist_ok=True)

        active_f = os.path.join(self.projects, "99999999-current.jsonl")
        _write_transcript(active_f, current_cwd)

        agent_f = os.path.join(self.projects, "agent-77777777.jsonl")
        _write_transcript(agent_f, repo)
        self._touch_ago(agent_f, 600)

        prior_f = os.path.join(self.projects, "88888888-prior.jsonl")
        _write_transcript(prior_f, repo, "resume the prior session work")
        self._touch_ago(prior_f, 600)

        older_prior_f = os.path.join(self.projects, "66666666-older-prior.jsonl")
        _write_transcript(older_prior_f, older_repo, "the older session work")
        self._touch_ago(older_prior_f, 1200)

        self._run("99999999-current", current_cwd)

        self.assertTrue(os.path.isfile(self.pointer))
        with open(self.pointer, encoding="utf-8") as fh:
            p = json.load(fh)
        self.assertEqual(p["session_id"], "88888888-prior")
        self.assertNotEqual(p["session_id"], "99999999-current")
        self.assertNotEqual(p["session_id"], "agent-77777777")
        self.assertNotEqual(p["session_id"], "66666666-older-prior")
        self.assertEqual(p["cwd"], repo)
        self.assertNotEqual(p["cwd"], older_repo)
        self.assertEqual(p["transcript_path"], prior_f)

    def test_2_no_settled_prior_session_silent_no_pointer(self):
        current_cwd = os.path.join(self.tmp, "currentcwd")
        os.makedirs(current_cwd, exist_ok=True)
        active_f = os.path.join(self.projects, "99999999-current.jsonl")
        _write_transcript(active_f, current_cwd)
        out = self._run("99999999-current", current_cwd)
        self.assertEqual(out, "")
        self.assertFalse(os.path.isfile(self.pointer))


if __name__ == "__main__":
    unittest.main()
