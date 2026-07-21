# np-test: refine-output | toggle/backend/re-entrancy gating, engine-repo
#          happy-path commit, no-empty-commit, and overlay-retarget (with/without
#          overlay) for np_agentic_cron.refine() -- Python port of
#          tests/maintain/test_refine_output.sh (deleted in the same commit).
"""Coverage floor: test_refine_output.sh's 5 PASS sections --
  1. re-entrancy (NERVEPACK_AGENT=1 -> bail, no log, engine HEAD frozen)
  2. stubbed happy path (path-limited, conventional-prefix, trailer-free commit
     in the ENGINE repo)
  3. no-empty-commit (agent finds nothing -> engine HEAD frozen)
  4a. overlay-retarget WITH overlay (prompt gets the 'Additional skill roots'
      note naming the overlay; cooperative agent commits into the OVERLAY only)
  4b. overlay-retarget NO overlay (no note; no overlay commit)
-- each ported 1:1 below, plus edge cases noticed during the port (toggle
gate on/off, backend pre-flight for both backends, missing/empty prompt, and
that refine -- unlike the content-gated crons -- proceeds WITHOUT an explicit
content dir since it commits to the engine). Mirrors
test_np_episodic_maintain.py's sandbox pattern and test_refine_output.sh's
recording/retarget stub for the extra_roots seam.
"""
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
    "# np-flow-scheduled-refine\n\nSome human-facing metadata.\n\n"
    "## Prompt\n\nLint frontmatter, audit cross-refs. Commit each fix.\n"
)

_ENV_KEYS = ("NP_CONTENT_DIR", "NERVEPACK_AGENT", "CLAUDE_BIN", "NP_LLM_AGENT_CMD",
             "NP_LLM_BACKEND", "REFINE_LOG")


def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class GatingAndPreflightTest(unittest.TestCase):
    """Each case bails before touching git (or is mocked past the agent call),
    so a sandboxed HOME (+ toggles + a patched engine root) is enough. refine is
    NOT content_gated and commits to the engine, so there is no content-skip
    case; instead we assert it proceeds without an explicit content dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "np")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        os.makedirs(os.path.join(self.np, "skills"))
        _write(os.path.join(self.np, "agents", "np-flow-scheduled-refine.md"), PROMPT_BODY)
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
        return os.path.join(self.home, ".cache", "nervepack", "refine.log")

    def _log_text(self):
        p = self._log_path()
        if not os.path.isfile(p):
            return ""
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    def _stub_claude(self):
        claude = os.path.join(self.tmp, "claude")
        _write(claude, "#!/usr/bin/env bash\ntrue\n")
        os.chmod(claude, 0o755)
        return claude

    # -- toggle gate (maintain.refine) ---------------------------------------
    def test_toggle_off_skips(self):
        _write(self.local, "maintain.refine=off\n")
        self.assertEqual(np_agentic_cron.refine(),
                         "skipped: maintain.refine disabled")

    def test_toggle_on_proceeds_past_gate(self):
        _write(self.local, "maintain.refine=on\n")
        self.assertNotEqual(np_agentic_cron.refine(),
                            "skipped: maintain.refine disabled")

    # -- refine is NOT content-gated: proceeds without an explicit content dir -
    def test_not_content_gated_proceeds_without_content_dir(self):
        _write(self.local, "maintain.refine=on\n")
        with mock.patch.dict(os.environ, {"CLAUDE_BIN": self._stub_claude()}), \
             mock.patch.object(np_agentic_cron.np_content, "merge_roots",
                               return_value=[]), \
             mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               return_value=True) as ra:
            result = np_agentic_cron.refine()
        # It reached the agent (not skipped on a content-dir gate) and committed
        # target resolved to the engine, not a content overlay.
        self.assertEqual(result, "ok: agent run completed")
        self.assertEqual(ra.call_args.kwargs.get("cwd"), self.np)

    # -- backend pre-flight ---------------------------------------------------
    def test_backend_claude_missing_binary_bails(self):
        _write(self.local, "maintain.refine=on\n")
        with mock.patch.dict(os.environ, {
                "NP_LLM_BACKEND": "claude",
                "CLAUDE_BIN": os.path.join(self.tmp, "no-such-claude")}):
            result = np_agentic_cron.refine()
        self.assertEqual(result, "skipped: claude CLI not found")
        self.assertIn("claude CLI not found", self._log_text())

    def test_backend_local_missing_cmd_bails(self):
        _write(self.local, "maintain.refine=on\n")
        os.environ.pop("NP_LLM_AGENT_CMD", None)
        with mock.patch.dict(os.environ, {"NP_LLM_BACKEND": "local"}):
            result = np_agentic_cron.refine()
        self.assertEqual(result, "skipped: NP_LLM_AGENT_CMD unset")
        self.assertIn("NP_LLM_AGENT_CMD", self._log_text())

    # -- re-entrancy (bash section 1) -----------------------------------------
    def test_reentrancy_bails_before_any_log(self):
        _write(self.local, "maintain.refine=on\n")
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            result = np_agentic_cron.refine()
        self.assertEqual(result,
                         "skipped: NERVEPACK_AGENT already set (re-entrant)")
        self.assertFalse(os.path.isfile(self._log_path()))

    # -- edge cases noticed during the port -----------------------------------
    def test_prompt_file_missing_returns_skip(self):
        _write(self.local, "maintain.refine=on\n")
        os.remove(os.path.join(self.np, "agents", "np-flow-scheduled-refine.md"))
        with mock.patch.dict(os.environ, {"CLAUDE_BIN": self._stub_claude()}):
            self.assertEqual(np_agentic_cron.refine(), "skipped: prompt missing")

    def test_empty_prompt_extracted_returns_skip(self):
        _write(self.local, "maintain.refine=on\n")
        _write(os.path.join(self.np, "agents", "np-flow-scheduled-refine.md"),
               "## Prompt\n")
        with mock.patch.dict(os.environ, {"CLAUDE_BIN": self._stub_claude()}):
            self.assertEqual(np_agentic_cron.refine(), "skipped: empty prompt")


class EngineCommitRoutingTest(unittest.TestCase):
    """Bash sections 2-3: a stubbed lint-fix agent commits into the ENGINE repo
    (refine's commit target) -- path-limited, conventional-prefix, trailer-free
    -- and a no-op agent leaves the engine HEAD untouched. merge_roots is
    stubbed to [] so the base prompt has no overlay note (isolating these
    sections from the extra_roots seam, which section 4 covers)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "engine")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        os.makedirs(os.path.join(self.np, "skills"))
        _write(os.path.join(self.np, "agents", "np-flow-scheduled-refine.md"), PROMPT_BODY)
        _git(self.np, "init", "-q")
        _git(self.np, "config", "user.email", "engine@agentjob.test")
        _git(self.np, "config", "user.name", "engine")
        _git(self.np, "add", "-A")
        _git(self.np, "commit", "-qm", "init")

        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.claude = os.path.join(self.tmp, "claude")
        _write(self.claude, "#!/usr/bin/env bash\ntrue\n")
        os.chmod(self.claude, 0o755)
        self.conf = os.path.join(self.tmp, "toggles.conf")
        _write(self.conf, "")
        self.local = os.path.join(self.tmp, "toggles.local")
        _write(self.local, "maintain.refine=on\n")

        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home,
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": self.local,
            "CLAUDE_BIN": self.claude,
        })
        self.env.start()
        self.np_patch = mock.patch.object(np_agentic_cron, "_NP", self.np)
        self.np_patch.start()
        self.mr_patch = mock.patch.object(
            np_agentic_cron.np_content, "merge_roots", return_value=[])
        self.mr_patch.start()

    def tearDown(self):
        self.mr_patch.stop()
        self.np_patch.stop()
        self.env.stop()
        for k in _ENV_KEYS:
            os.environ.pop(k, None)

    def _head(self, repo):
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()

    def _lintfix_stub(self):
        def _run(prompt, tools, cwd=None):
            base = cwd or self.np
            skill = os.path.join(base, "skills", "np-stub-lintfix")
            os.makedirs(skill, exist_ok=True)
            _write(os.path.join(skill, "SKILL.md"),
                   "---\nname: np-stub-lintfix\ndescription: stub.\n---\nFixed.\n")
            _git(base, "add", "skills/np-stub-lintfix/SKILL.md")
            _git(base, "commit", "-qm",
                 "skill(np-stub-lintfix): lint fix (stub)",
                 "--", "skills/np-stub-lintfix/SKILL.md")
            return True
        return _run

    # -- bash section 2: engine-repo happy path -------------------------------
    def test_happy_path_commits_land_in_engine(self):
        with mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               side_effect=self._lintfix_stub()):
            result = np_agentic_cron.refine()
        self.assertEqual(result, "ok: agent run completed")
        sha = subprocess.run(
            ["git", "-C", self.np, "log", "--format=%H\t%s"],
            capture_output=True, text=True).stdout
        line = [l for l in sha.splitlines() if "skill(np-stub-lintfix)" in l]
        self.assertTrue(line, "no skill(np-stub-lintfix) commit in the engine")
        commit = line[0].split("\t")[0]
        # path-limited: exactly the one skill file.
        files = subprocess.run(
            ["git", "-C", self.np, "diff-tree", "--no-commit-id",
             "--name-only", "-r", commit], capture_output=True, text=True).stdout
        self.assertEqual(files.strip(), "skills/np-stub-lintfix/SKILL.md")
        # conventional prefix + no LLM-attribution trailer.
        body = subprocess.run(
            ["git", "-C", self.np, "log", "-1", "--format=%B", commit],
            capture_output=True, text=True).stdout
        self.assertTrue(body.startswith("skill("))
        self.assertNotRegex(body.lower(), r"co-authored-by|generated with")

    # -- bash section 3: no-empty-commit --------------------------------------
    def test_no_op_when_agent_makes_no_commit(self):
        before = self._head(self.np)
        with mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               return_value=True):
            result = np_agentic_cron.refine()
        self.assertEqual(before, self._head(self.np))
        self.assertEqual(result, "ok: agent run completed")


class OverlayRetargetTest(unittest.TestCase):
    """Bash section 4 (the seam unique to the extra_roots crons): with an
    overlay resolving, _run injects the 'Additional skill roots' note naming the
    overlay, and a cooperative agent commits the overlay fix into the OVERLAY's
    own history, never the engine's; with no overlay, the note is absent and no
    overlay commit is fabricated. merge_roots is stubbed to control the root set
    deterministically (its own resolution is tested elsewhere) -- what refine
    adds, and what this asserts, is _extra_roots_note()'s note construction +
    injection into the prompt."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "engine")
        self.overlay = os.path.join(self.tmp, "overlay")
        os.makedirs(os.path.join(self.np, "agents"))
        os.makedirs(os.path.join(self.np, "skills"))
        _write(os.path.join(self.np, "agents", "np-flow-scheduled-refine.md"), PROMPT_BODY)
        os.makedirs(os.path.join(self.overlay, "skills", "np-overlay-existing"))
        _write(os.path.join(self.overlay, "skills", "np-overlay-existing", "SKILL.md"),
               "---\nname: np-overlay-existing\ndescription: pre-existing.\n---\nBody.\n")
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
        _write(self.local, "maintain.refine=on\n")
        self.captured = {}

        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home,
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": self.local,
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

    def _recording_retarget_stub(self):
        """Records the prompt; if it names an overlay via the driver's
        'rooted at `<path>`' phrasing, commits an overlay-skill fix into THAT
        path via git -C -- exactly what np-flow-scheduled-refine.md instructs a
        real agent to do. No such phrasing -> no overlay commit."""
        import re

        def _run(prompt, tools, cwd=None):
            self.captured["prompt"] = prompt
            m = re.search(r"rooted at `([^`]*)`", prompt)
            if m and os.path.isdir(os.path.join(m.group(1), ".git")):
                path = m.group(1)
                skill = os.path.join(path, "skills", "np-overlay-target")
                os.makedirs(skill, exist_ok=True)
                _write(os.path.join(skill, "SKILL.md"),
                       "---\nname: np-overlay-target\ndescription: overlay fix.\n---\nBody.\n")
                _git(path, "add", "skills/np-overlay-target/SKILL.md")
                _git(path, "commit", "-qm",
                     "skill(np-overlay-target): overlay fix (stub)",
                     "--", "skills/np-overlay-target/SKILL.md")
            return True
        return _run

    def _log_oneline(self, repo):
        return subprocess.run(["git", "-C", repo, "log", "--oneline"],
                              capture_output=True, text=True).stdout

    # -- 4a: WITH overlay -> note present, overlay gets the commit, engine does not
    def test_with_overlay_injects_note_and_commits_overlay_only(self):
        engine_before = subprocess.run(
            ["git", "-C", self.np, "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        with mock.patch.object(np_agentic_cron.np_content, "merge_roots",
                               return_value=[self.overlay]), \
             mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               side_effect=self._recording_retarget_stub()):
            result = np_agentic_cron.refine()
        self.assertEqual(result, "ok: agent run completed")
        prompt = self.captured.get("prompt", "")
        self.assertIn("Additional skill roots", prompt)
        self.assertIn(self.overlay, prompt)
        # fix landed in the overlay, not the engine
        self.assertIn("np-overlay-target", self._log_oneline(self.overlay))
        self.assertNotIn("np-overlay-target", self._log_oneline(self.np))
        engine_after = subprocess.run(
            ["git", "-C", self.np, "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(engine_before, engine_after)

    # -- 4b: NO overlay -> note absent, no overlay commit ---------------------
    def test_without_overlay_no_note_no_overlay_commit(self):
        with mock.patch.object(np_agentic_cron.np_content, "merge_roots",
                               return_value=[]), \
             mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               side_effect=self._recording_retarget_stub()):
            result = np_agentic_cron.refine()
        self.assertEqual(result, "ok: agent run completed")
        self.assertNotIn("Additional skill roots", self.captured.get("prompt", ""))
        self.assertNotIn("np-overlay-target", self._log_oneline(self.overlay))


if __name__ == "__main__":
    unittest.main()
