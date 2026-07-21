# np-test: compact-output | toggle/backend/re-entrancy gating, TWO-COMMIT
#          contract, no-empty-commit, overlay-retarget (with/without overlay),
#          and unwritable-log fail-open for np_agentic_cron.compact() -- Python
#          port of tests/maintain/test_compact_output.sh (deleted in the same
#          commit), and the compact half of the now-retired shared seam tests
#          test_toggle_gating.sh / test_fail_open.sh / test_backend_preflight.sh
#          / test_hook_bail_unwritable_log.sh (all git rm'd here, their compact
#          coverage folded in below).
"""Coverage floor:
  test_compact_output.sh's 5 PASS sections --
    1. re-entrancy (NERVEPACK_AGENT=1 -> bail, no log, engine HEAD frozen)
    2. TWO-COMMIT contract (Commit A = archive `skill(...)`, Commit B =
       proposal `maintain(...)`; each path-limited, conventional, trailer-free,
       both in the ENGINE repo, two DISTINCT commits)
    3. no-empty-commit (agent finds nothing -> engine HEAD frozen)
    4a. overlay-retarget WITH overlay (note present, names overlay; fix into
        overlay only)
    4b. overlay-retarget NO overlay (note absent, no overlay commit)
  + the compact arm of the retired shared seam tests: toggle off/on,
    backend pre-flight (claude-no-bin, local-no-cmd), and the unwritable-log
    fail-open invariant (bail() degrades instead of crashing when its log path
    is unwritable).
  + compact-specific note text (steps 2-5 + the archive/compact-proposals/
    plugin.json per-root detail that distinguishes it from refine's note).
Mirrors tests/maintain/test_np_refine.py's structure.
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
    "# np-flow-weekly-compact\n\nSome human-facing metadata.\n\n"
    "## Prompt\n\nDedup near-identical skills; propose splits. Two commits.\n"
)

_ENV_KEYS = ("NP_CONTENT_DIR", "NERVEPACK_AGENT", "CLAUDE_BIN", "NP_LLM_AGENT_CMD",
             "NP_LLM_BACKEND", "COMPACT_LOG")


def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class GatingAndPreflightTest(unittest.TestCase):
    """Absorbs the compact arm of the retired shared seam tests: toggle off/on,
    backend pre-flight (both backends), re-entrancy, missing/empty prompt, and
    the unwritable-log fail-open invariant (from test_hook_bail_unwritable_log.sh).
    Each case bails before the agent call, so a sandboxed HOME + toggles + a
    patched engine root is enough."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "np")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        os.makedirs(os.path.join(self.np, "skills"))
        _write(os.path.join(self.np, "agents", "np-flow-weekly-compact.md"), PROMPT_BODY)
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
        return os.path.join(self.home, ".cache", "nervepack", "compact.log")

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

    # -- toggle gate (maintain.compact) --------------------------------------
    def test_toggle_off_skips(self):
        _write(self.local, "maintain.compact=off\n")
        self.assertEqual(np_agentic_cron.compact(),
                         "skipped: maintain.compact disabled")

    def test_toggle_on_proceeds_past_gate(self):
        _write(self.local, "maintain.compact=on\n")
        self.assertNotEqual(np_agentic_cron.compact(),
                            "skipped: maintain.compact disabled")

    # -- backend pre-flight ---------------------------------------------------
    def test_backend_claude_missing_binary_bails(self):
        _write(self.local, "maintain.compact=on\n")
        with mock.patch.dict(os.environ, {
                "NP_LLM_BACKEND": "claude",
                "CLAUDE_BIN": os.path.join(self.tmp, "no-such-claude")}):
            result = np_agentic_cron.compact()
        self.assertEqual(result, "skipped: claude CLI not found")
        self.assertIn("claude CLI not found", self._log_text())

    def test_backend_local_missing_cmd_bails(self):
        _write(self.local, "maintain.compact=on\n")
        os.environ.pop("NP_LLM_AGENT_CMD", None)
        with mock.patch.dict(os.environ, {"NP_LLM_BACKEND": "local"}):
            result = np_agentic_cron.compact()
        self.assertEqual(result, "skipped: NP_LLM_AGENT_CMD unset")
        self.assertIn("NP_LLM_AGENT_CMD", self._log_text())

    # -- re-entrancy (bash section 1) -----------------------------------------
    def test_reentrancy_bails_before_any_log(self):
        _write(self.local, "maintain.compact=on\n")
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            result = np_agentic_cron.compact()
        self.assertEqual(result,
                         "skipped: NERVEPACK_AGENT already set (re-entrant)")
        self.assertFalse(os.path.isfile(self._log_path()))

    # -- unwritable-log fail-open (from test_hook_bail_unwritable_log.sh) -----
    def test_unwritable_log_bail_degrades_not_crashes(self):
        # Make the log's parent a FILE so os.makedirs in _log() cannot succeed;
        # a backend-missing bail then tries to log there. The invariant: compact()
        # still returns a status (never raises), and no log file is created.
        _write(self.local, "maintain.compact=on\n")
        blocker = os.path.join(self.tmp, "blocker")
        _write(blocker, "i am a file, not a dir\n")
        unwritable = os.path.join(blocker, "compact.log")   # parent is a file
        with mock.patch.dict(os.environ, {
                "COMPACT_LOG": unwritable, "NP_LLM_BACKEND": "claude",
                "CLAUDE_BIN": os.path.join(self.tmp, "no-such-claude")}):
            result = np_agentic_cron.compact()   # must not raise
        self.assertEqual(result, "skipped: claude CLI not found")
        self.assertFalse(os.path.exists(unwritable))
        self.assertTrue(os.path.isfile(blocker))   # blocker not clobbered

    # -- edge cases -----------------------------------------------------------
    def test_prompt_file_missing_returns_skip(self):
        _write(self.local, "maintain.compact=on\n")
        os.remove(os.path.join(self.np, "agents", "np-flow-weekly-compact.md"))
        with mock.patch.dict(os.environ, {"CLAUDE_BIN": self._stub_claude()}):
            self.assertEqual(np_agentic_cron.compact(), "skipped: prompt missing")

    def test_empty_prompt_extracted_returns_skip(self):
        _write(self.local, "maintain.compact=on\n")
        _write(os.path.join(self.np, "agents", "np-flow-weekly-compact.md"),
               "## Prompt\n")
        with mock.patch.dict(os.environ, {"CLAUDE_BIN": self._stub_claude()}):
            self.assertEqual(np_agentic_cron.compact(), "skipped: empty prompt")


class TwoCommitContractTest(unittest.TestCase):
    """Bash section 2-3: a stubbed dedup agent makes Commit A (archive the
    duplicate, `skill(...)` prefix) then Commit B (a review proposal,
    `maintain(...)` prefix) -- both in the ENGINE repo (compact's commit target),
    each path-limited, conventional, trailer-free, two DISTINCT commits; and a
    no-op agent leaves the engine HEAD untouched. merge_roots is stubbed to [] so
    the base prompt carries no overlay note (isolating these from section 4)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "engine")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        os.makedirs(os.path.join(self.np, "skills"))
        _write(os.path.join(self.np, "agents", "np-flow-weekly-compact.md"), PROMPT_BODY)
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
        _write(self.local, "maintain.compact=on\n")

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

    def _dedup_two_commit_stub(self):
        def _run(prompt, tools, cwd=None):
            base = cwd or self.np
            # Commit A: archive the duplicate (skill( prefix)
            a = os.path.join(base, "archive", "np-stub-dup")
            os.makedirs(a, exist_ok=True)
            _write(os.path.join(a, "SKILL.md"), "archived (stub)\n")
            _git(base, "add", "archive/np-stub-dup/SKILL.md")
            _git(base, "commit", "-qm", "skill(np-stub-dup): archive duplicate (stub)",
                 "--", "archive/np-stub-dup/SKILL.md")
            # Commit B: a review proposal (maintain( prefix)
            p = os.path.join(base, "compact-proposals")
            os.makedirs(p, exist_ok=True)
            _write(os.path.join(p, "stub-proposal.md"), "proposal (stub)\n")
            _git(base, "add", "compact-proposals/stub-proposal.md")
            _git(base, "commit", "-qm", "maintain(compact): propose merge (stub)",
                 "--", "compact-proposals/stub-proposal.md")
            return True
        return _run

    def _commit_for(self, subject_substr):
        out = subprocess.run(
            ["git", "-C", self.np, "log", "--format=%H\t%s"],
            capture_output=True, text=True).stdout
        for line in out.splitlines():
            if subject_substr in line:
                return line.split("\t")[0]
        return ""

    def _files_in(self, sha):
        return subprocess.run(
            ["git", "-C", self.np, "diff-tree", "--no-commit-id", "--name-only",
             "-r", sha], capture_output=True, text=True).stdout.strip()

    def _body(self, sha):
        return subprocess.run(
            ["git", "-C", self.np, "log", "-1", "--format=%B", sha],
            capture_output=True, text=True).stdout

    # -- bash section 2: two-commit contract ----------------------------------
    def test_two_commit_contract_in_engine(self):
        with mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               side_effect=self._dedup_two_commit_stub()):
            result = np_agentic_cron.compact()
        self.assertEqual(result, "ok: agent run completed")
        sha_a = self._commit_for("archive duplicate (stub)")
        sha_b = self._commit_for("propose merge (stub)")
        self.assertTrue(sha_a, "no Commit A (archive) in the engine")
        self.assertTrue(sha_b, "no Commit B (proposal) in the engine")
        self.assertNotEqual(sha_a, sha_b, "expected two DISTINCT commits")
        # Commit A: path-limited to the archived duplicate, skill( prefix, no trailer.
        self.assertEqual(self._files_in(sha_a), "archive/np-stub-dup/SKILL.md")
        self.assertTrue(self._body(sha_a).startswith("skill("))
        self.assertNotRegex(self._body(sha_a).lower(), r"co-authored-by|generated with")
        # Commit B: path-limited to the proposal, maintain( prefix, no trailer.
        self.assertEqual(self._files_in(sha_b), "compact-proposals/stub-proposal.md")
        self.assertTrue(self._body(sha_b).startswith("maintain("))
        self.assertNotRegex(self._body(sha_b).lower(), r"co-authored-by|generated with")

    # -- bash section 3: no-empty-commit --------------------------------------
    def test_no_op_when_agent_makes_no_commit(self):
        before = self._head(self.np)
        with mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               return_value=True):
            result = np_agentic_cron.compact()
        self.assertEqual(before, self._head(self.np))
        self.assertEqual(result, "ok: agent run completed")


class OverlayRetargetTest(unittest.TestCase):
    """Bash section 4 + the compact-specific note text: with an overlay
    resolving, _run injects the 'Additional skill roots' note naming the overlay
    AND using compact's own wording (steps 2-5 + the archive/compact-proposals/
    plugin.json per-root detail), and a cooperative agent commits the overlay fix
    into the OVERLAY only; with no overlay, the note is absent and no overlay
    commit. merge_roots is stubbed to control the root set deterministically."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "engine")
        self.overlay = os.path.join(self.tmp, "overlay")
        os.makedirs(os.path.join(self.np, "agents"))
        os.makedirs(os.path.join(self.np, "skills"))
        _write(os.path.join(self.np, "agents", "np-flow-weekly-compact.md"), PROMPT_BODY)
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
        _write(self.local, "maintain.compact=on\n")
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
        import re

        def _run(prompt, tools, cwd=None):
            self.captured["prompt"] = prompt
            m = re.search(r"rooted at `([^`]*)`", prompt)
            if m and os.path.isdir(os.path.join(m.group(1), ".git")):
                path = m.group(1)
                d = os.path.join(path, "archive", "np-overlay-dup")
                os.makedirs(d, exist_ok=True)
                _write(os.path.join(d, "SKILL.md"), "archived (overlay stub)\n")
                _git(path, "add", "archive/np-overlay-dup/SKILL.md")
                _git(path, "commit", "-qm",
                     "skill(np-overlay-dup): archive duplicate (overlay stub)",
                     "--", "archive/np-overlay-dup/SKILL.md")
            return True
        return _run

    def _log_oneline(self, repo):
        return subprocess.run(["git", "-C", repo, "log", "--oneline"],
                              capture_output=True, text=True).stdout

    def test_with_overlay_injects_compact_note_and_commits_overlay_only(self):
        engine_before = subprocess.run(
            ["git", "-C", self.np, "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        with mock.patch.object(np_agentic_cron.np_content, "merge_roots",
                               return_value=[self.overlay]), \
             mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               side_effect=self._recording_retarget_stub()):
            result = np_agentic_cron.compact()
        self.assertEqual(result, "ok: agent run completed")
        prompt = self.captured.get("prompt", "")
        self.assertIn("Additional skill roots", prompt)
        self.assertIn(self.overlay, prompt)
        # compact-specific note wording (distinguishes it from refine's note):
        self.assertIn("apply steps 2-5", prompt)
        self.assertIn("compact-proposals/", prompt)
        # fix landed in the overlay, not the engine
        self.assertIn("np-overlay-dup", self._log_oneline(self.overlay))
        self.assertNotIn("np-overlay-dup", self._log_oneline(self.np))
        engine_after = subprocess.run(
            ["git", "-C", self.np, "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(engine_before, engine_after)

    def test_without_overlay_no_note_no_overlay_commit(self):
        with mock.patch.object(np_agentic_cron.np_content, "merge_roots",
                               return_value=[]), \
             mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               side_effect=self._recording_retarget_stub()):
            result = np_agentic_cron.compact()
        self.assertEqual(result, "ok: agent run completed")
        self.assertNotIn("Additional skill roots", self.captured.get("prompt", ""))
        self.assertNotIn("np-overlay-dup", self._log_oneline(self.overlay))


if __name__ == "__main__":
    unittest.main()
