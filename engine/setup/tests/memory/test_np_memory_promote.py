# np-test: memory-promote-cron | gating, content-skip, backend-preflight,
#          re-entrancy, stubbed-agent commit routing for np_agentic_cron.memory_promote()
#          -- Python port of tests/memory/test_memory_promote.sh (bash body deleted
#          in the same commit that ports it).
"""Coverage floor: the bash suite's 6 sections (9 PASS assertions) --
toggle gate, content-dir-explicit skip (issue #12), backend pre-flight
(claude + local backend), re-entrancy, and stubbed-agent commit routing
(happy path + no-op) -- each ported 1:1 below, plus two edge cases
(missing/empty prompt file) noticed during the port."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.abspath(os.path.join(HERE, "..", ".."))  # engine/setup
if SETUP not in sys.path:
    sys.path.insert(0, SETUP)

import np_agentic_cron  # noqa: E402

PROMPT_BODY = (
    "# memory-promote\n\nSome human-facing metadata.\n\n"
    "## Prompt\n\nYou are a scheduled task. Do the work.\n"
)

_ENV_KEYS = ("NP_CONTENT_DIR", "NERVEPACK_AGENT", "CLAUDE_BIN", "NP_LLM_AGENT_CMD",
             "NP_LLM_BACKEND", "MEMORY_PROMOTE_LOG")


def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class GatingAndPreflightTest(unittest.TestCase):
    """Sections 1-4 of the bash suite: each bails before touching git, so a
    sandboxed HOME (+ toggles) is enough -- no repos needed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "np")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        _write(os.path.join(self.np, "agents", "np-flow-memory-promote.md"), PROMPT_BODY)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.conf = os.path.join(self.tmp, "toggles.conf")
        self.local = os.path.join(self.tmp, "toggles.local")
        _write(self.conf, "")
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home,
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": self.local,
        })
        self.env.start()
        self.np_patch = mock.patch.object(np_agentic_cron, "_NP", self.np)
        self.np_patch.start()

    def tearDown(self):
        self.np_patch.stop()
        self.env.stop()
        for k in _ENV_KEYS:
            os.environ.pop(k, None)

    def _log_path(self):
        return os.path.join(self.home, ".cache", "nervepack", "memory-promote.log")

    def _log_text(self):
        p = self._log_path()
        if not os.path.isfile(p):
            return ""
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    # -- Section 1: toggle gate ---------------------------------------------
    def test_toggle_off_skips(self):
        _write(self.local, "memory.promote=off\n")
        result = np_agentic_cron.memory_promote()
        self.assertEqual(result, "skipped: memory.promote disabled")

    def test_toggle_on_proceeds_past_gate(self):
        _write(self.local, "memory.promote=on\n")
        result = np_agentic_cron.memory_promote()
        self.assertNotEqual(result, "skipped: memory.promote disabled")

    # -- Section 2: content-dir-explicit skip (issue #12) --------------------
    def test_content_implicit_fallback_skips(self):
        _write(self.local, "memory.promote=on\n")
        result = np_agentic_cron.memory_promote()
        self.assertEqual(
            result, "skipped: content dir is the implicit engine-root fallback")
        self.assertIn("skipped: content dir is the implicit engine-root fallback",
                       self._log_text())

    # -- Section 3: backend pre-flight ---------------------------------------
    def test_backend_claude_missing_binary_bails(self):
        _write(self.local, "memory.promote=on\n")
        content = os.path.join(self.tmp, "content")
        os.makedirs(content, exist_ok=True)
        with mock.patch.dict(os.environ, {
                "NP_CONTENT_DIR": content, "NP_LLM_BACKEND": "claude",
                "CLAUDE_BIN": os.path.join(self.tmp, "no-such-claude")}):
            result = np_agentic_cron.memory_promote()
        self.assertEqual(result, "skipped: claude CLI not found")
        self.assertIn("claude CLI not found", self._log_text())

    def test_backend_local_missing_cmd_bails(self):
        _write(self.local, "memory.promote=on\n")
        content = os.path.join(self.tmp, "content")
        os.makedirs(content, exist_ok=True)
        os.environ.pop("NP_LLM_AGENT_CMD", None)
        with mock.patch.dict(os.environ, {
                "NP_CONTENT_DIR": content, "NP_LLM_BACKEND": "local"}):
            result = np_agentic_cron.memory_promote()
        self.assertEqual(result, "skipped: NP_LLM_AGENT_CMD unset")
        self.assertIn("NP_LLM_AGENT_CMD", self._log_text())

    # -- Section 4: re-entrancy ------------------------------------------------
    def test_reentrancy_bails_before_any_log(self):
        _write(self.local, "memory.promote=on\n")
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            result = np_agentic_cron.memory_promote()
        self.assertEqual(result, "skipped: NERVEPACK_AGENT already set (re-entrant)")
        self.assertFalse(os.path.isfile(self._log_path()))

    # -- Edge cases noticed during the port (not in the bash floor) ----------
    def test_prompt_file_missing_returns_skip(self):
        _write(self.local, "memory.promote=on\n")
        content = os.path.join(self.tmp, "content")
        os.makedirs(content, exist_ok=True)
        os.remove(os.path.join(self.np, "agents", "np-flow-memory-promote.md"))
        claude = os.path.join(self.tmp, "claude")
        _write(claude, "#!/usr/bin/env bash\ntrue\n")
        os.chmod(claude, 0o755)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": content, "CLAUDE_BIN": claude}):
            result = np_agentic_cron.memory_promote()
        self.assertEqual(result, "skipped: prompt missing")

    def test_empty_prompt_extracted_returns_skip(self):
        _write(self.local, "memory.promote=on\n")
        content = os.path.join(self.tmp, "content")
        os.makedirs(content, exist_ok=True)
        _write(os.path.join(self.np, "agents", "np-flow-memory-promote.md"), "## Prompt\n")
        claude = os.path.join(self.tmp, "claude")
        _write(claude, "#!/usr/bin/env bash\ntrue\n")
        os.chmod(claude, 0o755)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": content, "CLAUDE_BIN": claude}):
            result = np_agentic_cron.memory_promote()
        self.assertEqual(result, "skipped: empty prompt")


class CommitRoutingTest(unittest.TestCase):
    """Sections 5-6 of the bash suite: a stubbed agent commits into the
    content overlay only, never the engine (happy path); and a no-op agent
    run leaves the overlay HEAD untouched (no fabricated commit)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "engine")
        self.overlay = os.path.join(self.tmp, "overlay")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        os.makedirs(os.path.join(self.np, "skills"))
        _write(os.path.join(self.np, "agents", "np-flow-memory-promote.md"), PROMPT_BODY)
        _write(os.path.join(self.overlay, "README.md"), "overlay sandbox\n")
        for repo, email in ((self.np, "engine@agentjob.test"),
                             (self.overlay, "overlay@agentjob.test")):
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", email)
            _git(repo, "config", "user.name", email.split("@")[0])
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "init")

        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.claude = os.path.join(self.tmp, "claude")
        _write(self.claude, "#!/usr/bin/env bash\ntrue\n")
        os.chmod(self.claude, 0o755)
        self.conf = os.path.join(self.tmp, "toggles.conf")
        _write(self.conf, "")
        self.local = os.path.join(self.tmp, "toggles.local")
        _write(self.local, "memory.promote=on\n")

        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home,
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": self.local,
            "NP_CONTENT_DIR": self.overlay,
            "CLAUDE_BIN": self.claude,
        })
        self.env.start()
        self.np_patch = mock.patch.object(np_agentic_cron, "_NP", self.np)
        self.np_patch.start()

    def tearDown(self):
        self.np_patch.stop()
        self.env.stop()
        for k in _ENV_KEYS:
            os.environ.pop(k, None)

    def _head(self, repo):
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout.strip()

    def _log_oneline(self, repo):
        return subprocess.run(["git", "-C", repo, "log", "--oneline"],
                               capture_output=True, text=True).stdout

    def _promote_stub(self):
        def _run(prompt, tools, cwd=None):
            base = cwd or self.overlay
            skill = os.path.join(base, "skills", "np-stub-promoted")
            os.makedirs(skill, exist_ok=True)
            _write(os.path.join(skill, "SKILL.md"),
                   "---\nname: np-stub-promoted\ndescription: stub-promoted skill.\n"
                   "---\nStub body.\n")
            _git(base, "add", "skills/np-stub-promoted")
            _git(base, "commit", "-qm",
                 "skill(np-stub-promoted): promote from memory (stub)")
            return True
        return _run

    def test_happy_path_commits_land_in_overlay_not_engine(self):
        engine_before = self._head(self.np)
        with mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               side_effect=self._promote_stub()):
            result = np_agentic_cron.memory_promote()
        self.assertTrue(os.path.isfile(
            os.path.join(self.overlay, "skills", "np-stub-promoted", "SKILL.md")))
        self.assertIn("skill(", self._log_oneline(self.overlay))
        self.assertNotIn("skill(", self._log_oneline(self.np))
        self.assertEqual(engine_before, self._head(self.np))
        self.assertEqual(result, "ok: agent run completed")

    def test_no_op_when_agent_makes_no_commit(self):
        overlay_before = self._head(self.overlay)
        with mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               return_value=True):
            result = np_agentic_cron.memory_promote()
        self.assertEqual(overlay_before, self._head(self.overlay))
        self.assertEqual(result, "ok: agent run completed")


if __name__ == "__main__":
    unittest.main()
