# np-test: episodic-maintain-cron | gating, content-skip, backend-preflight,
#          re-entrancy, stubbed-agent commit routing, and real stdin invocation
#          for np_agentic_cron.episodic_maintain() -- Python port of
#          tests/episodic/test_maintain_output.sh AND
#          tests/episodic/test_maintain_invocation.sh (both bash bodies deleted
#          in the same commit that ports them).
"""Coverage floor: test_maintain_output.sh's 3 PASS sections (content-skip,
committed-output happy path, no-empty-commit) + test_maintain_invocation.sh's
1 PASS (prompt reaches the agent via stdin, not a positional CLI arg) -- 4
cases total, each ported 1:1 below -- plus edge cases noticed during the port
(toggle gate on/off, backend pre-flight for both backends, re-entrancy,
missing/empty prompt file), following test_np_memory_promote.py's sandbox
pattern for the shared cases and agentjob.sh's `episodic-drain` stub shape for
the commit-routing cases."""
import os
import stat
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
    "# np-flow-episodic-maintain\n\nSome human-facing metadata.\n\n"
    "## Prompt\n\nYou are a scheduled task. Do the work.\n"
)

_ENV_KEYS = ("NP_CONTENT_DIR", "NERVEPACK_AGENT", "CLAUDE_BIN", "NP_LLM_AGENT_CMD",
             "NP_LLM_BACKEND", "EPISODIC_MAINTAIN_LOG")


def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class GatingAndPreflightTest(unittest.TestCase):
    """Each case bails before touching git, so a sandboxed HOME (+ toggles) is
    enough -- no repos needed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "np")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        _write(os.path.join(self.np, "agents", "np-flow-episodic-maintain.md"), PROMPT_BODY)
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
        return os.path.join(self.home, ".cache", "nervepack", "episodic-maintain.log")

    def _log_text(self):
        p = self._log_path()
        if not os.path.isfile(p):
            return ""
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    # -- toggle gate (memory.maintain) ---------------------------------------
    def test_toggle_off_skips(self):
        _write(self.local, "memory.maintain=off\n")
        result = np_agentic_cron.episodic_maintain()
        self.assertEqual(result, "skipped: memory.maintain disabled")

    def test_toggle_on_proceeds_past_gate(self):
        _write(self.local, "memory.maintain=on\n")
        result = np_agentic_cron.episodic_maintain()
        self.assertNotEqual(result, "skipped: memory.maintain disabled")

    # -- content-dir-explicit skip (issue #12), bash section 1 ---------------
    def test_content_implicit_fallback_skips(self):
        _write(self.local, "memory.maintain=on\n")
        result = np_agentic_cron.episodic_maintain()
        self.assertEqual(
            result, "skipped: content dir is the implicit engine-root fallback")
        log = self._log_text()
        self.assertIn("skipped: content dir is the implicit engine-root fallback", log)
        # Task 0 review Minor #1: the log detail is now derived from cfg.name
        # (cron-neutral), not hardcoded to memory-promote's wording.
        self.assertIn("to enable episodic-maintain", log)

    # -- backend pre-flight ---------------------------------------------------
    def test_backend_claude_missing_binary_bails(self):
        _write(self.local, "memory.maintain=on\n")
        content = os.path.join(self.tmp, "content")
        os.makedirs(content, exist_ok=True)
        with mock.patch.dict(os.environ, {
                "NP_CONTENT_DIR": content, "NP_LLM_BACKEND": "claude",
                "CLAUDE_BIN": os.path.join(self.tmp, "no-such-claude")}):
            result = np_agentic_cron.episodic_maintain()
        self.assertEqual(result, "skipped: claude CLI not found")
        self.assertIn("claude CLI not found", self._log_text())

    def test_backend_local_missing_cmd_bails(self):
        _write(self.local, "memory.maintain=on\n")
        content = os.path.join(self.tmp, "content")
        os.makedirs(content, exist_ok=True)
        os.environ.pop("NP_LLM_AGENT_CMD", None)
        with mock.patch.dict(os.environ, {
                "NP_CONTENT_DIR": content, "NP_LLM_BACKEND": "local"}):
            result = np_agentic_cron.episodic_maintain()
        self.assertEqual(result, "skipped: NP_LLM_AGENT_CMD unset")
        self.assertIn("NP_LLM_AGENT_CMD", self._log_text())

    # -- re-entrancy ------------------------------------------------------------
    def test_reentrancy_bails_before_any_log(self):
        _write(self.local, "memory.maintain=on\n")
        with mock.patch.dict(os.environ, {"NERVEPACK_AGENT": "1"}):
            result = np_agentic_cron.episodic_maintain()
        self.assertEqual(result, "skipped: NERVEPACK_AGENT already set (re-entrant)")
        self.assertFalse(os.path.isfile(self._log_path()))

    # -- edge cases noticed during the port (not in the bash floor) ----------
    def test_prompt_file_missing_returns_skip(self):
        _write(self.local, "memory.maintain=on\n")
        content = os.path.join(self.tmp, "content")
        os.makedirs(content, exist_ok=True)
        os.remove(os.path.join(self.np, "agents", "np-flow-episodic-maintain.md"))
        claude = os.path.join(self.tmp, "claude")
        _write(claude, "#!/usr/bin/env bash\ntrue\n")
        os.chmod(claude, 0o755)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": content, "CLAUDE_BIN": claude}):
            result = np_agentic_cron.episodic_maintain()
        self.assertEqual(result, "skipped: prompt missing")

    def test_empty_prompt_extracted_returns_skip(self):
        _write(self.local, "memory.maintain=on\n")
        content = os.path.join(self.tmp, "content")
        os.makedirs(content, exist_ok=True)
        _write(os.path.join(self.np, "agents", "np-flow-episodic-maintain.md"), "## Prompt\n")
        claude = os.path.join(self.tmp, "claude")
        _write(claude, "#!/usr/bin/env bash\ntrue\n")
        os.chmod(claude, 0o755)
        with mock.patch.dict(os.environ, {"NP_CONTENT_DIR": content, "CLAUDE_BIN": claude}):
            result = np_agentic_cron.episodic_maintain()
        self.assertEqual(result, "skipped: empty prompt")


class CommitRoutingTest(unittest.TestCase):
    """Bash sections 2-3 of test_maintain_output.sh: a stubbed agent (the
    `episodic-drain` shape from agentjob.sh) drains a note into the content
    overlay only, never the engine (happy path); and a no-op agent run (empty
    inbox) leaves the overlay HEAD untouched (no fabricated commit)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "engine")
        self.overlay = os.path.join(self.tmp, "overlay")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        os.makedirs(os.path.join(self.np, "skills"))
        _write(os.path.join(self.np, "agents", "np-flow-episodic-maintain.md"), PROMPT_BODY)
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
        _write(self.local, "memory.maintain=on\n")

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

    def _episodic_drain_stub(self):
        def _run(prompt, tools, cwd=None):
            base = cwd or self.overlay
            os.makedirs(os.path.join(base, "memory", "episodic"), exist_ok=True)
            note = os.path.join(base, "memory", "episodic", "stub-topic.md")
            with open(note, "a", encoding="utf-8") as fh:
                fh.write("## drained entry\nstub note.\n")
            _git(base, "add", "memory/episodic/stub-topic.md")
            _git(base, "commit", "-qm", "episodic(stub-topic): drain inbox (stub)")
            return True
        return _run

    # -- bash section 2: committed-output happy path -------------------------
    def test_happy_path_commits_land_in_overlay_not_engine(self):
        engine_before = self._head(self.np)
        with mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               side_effect=self._episodic_drain_stub()):
            result = np_agentic_cron.episodic_maintain()
        note = os.path.join(self.overlay, "memory", "episodic", "stub-topic.md")
        self.assertTrue(os.path.isfile(note))
        with open(note, encoding="utf-8") as fh:
            self.assertIn("drained entry", fh.read())
        self.assertIn("episodic(", self._log_oneline(self.overlay))
        self.assertNotIn("episodic(", self._log_oneline(self.np))
        self.assertEqual(engine_before, self._head(self.np))
        self.assertEqual(result, "ok: agent run completed")

    # -- bash section 3: no-empty-commit --------------------------------------
    def test_no_op_when_agent_makes_no_commit(self):
        overlay_before = self._head(self.overlay)
        with mock.patch.object(np_agentic_cron.np_llm_agent, "run_agent",
                               return_value=True):
            result = np_agentic_cron.episodic_maintain()
        self.assertEqual(overlay_before, self._head(self.overlay))
        self.assertEqual(result, "ok: agent run completed")


class InvocationTest(unittest.TestCase):
    """Port of test_maintain_invocation.sh: a real (unmocked) end-to-end call
    through np_llm_agent.run_agent -> np-llm.sh -> a stub CLAUDE_BIN, proving
    the prompt reaches the agent over STDIN rather than being lost as a
    trailing positional after the variadic `--allowedTools` (the historical
    bug class -- see test_capture_invocation.sh's sibling note). Since the
    ported architecture routes agent stdout/stderr to DEVNULL (np_llm_agent.py)
    rather than appending it to the cron's own log, the observable proof is
    episodic_maintain()'s return status (ok vs failed), not log content -- the
    stub exits nonzero iff stdin arrived empty, so a regression here surfaces
    as "agent run failed" instead of "ok: agent run completed". Also exercises
    the EPISODIC_MAINTAIN_LOG override, mirroring the bash test's own use of it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.np = os.path.join(self.tmp, "np")
        os.makedirs(os.path.join(self.np, "engine", "setup"))
        os.makedirs(os.path.join(self.np, "agents"))
        _write(os.path.join(self.np, "agents", "np-flow-episodic-maintain.md"),
               "# np-flow-episodic-maintain\n\n## Prompt\n"
               "Summarise the session for episodic memory. Return a brief JSON note.\n")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.overlay = os.path.join(self.tmp, "overlay")
        os.makedirs(self.overlay)
        self.conf = os.path.join(self.tmp, "toggles.conf")
        _write(self.conf, "")
        self.local = os.path.join(self.tmp, "toggles.local")
        _write(self.local, "memory.maintain=on\n")
        self.log = os.path.join(self.tmp, "maintain.log")

        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        self.env = mock.patch.dict(os.environ, {
            "HOME": self.home,
            "NP_TOGGLES_CONF": self.conf,
            "NP_TOGGLES_LOCAL": self.local,
            "NP_CONTENT_DIR": self.overlay,
            "NP_LLM_BACKEND": "claude",
            "EPISODIC_MAINTAIN_LOG": self.log,
        })
        self.env.start()
        self.np_patch = mock.patch.object(np_agentic_cron, "_NP", self.np)
        self.np_patch.start()

    def tearDown(self):
        self.np_patch.stop()
        self.env.stop()
        for k in _ENV_KEYS:
            os.environ.pop(k, None)

    def _write_variadic_eating_stub(self):
        # Same shape as test_maintain_invocation.sh's stub: mimics a `claude`
        # binary whose `--allowedTools` is variadic (swallows following
        # positional args until the next flag), so a bug that passed the
        # prompt as a trailing positional instead of stdin would starve it.
        claude = os.path.join(self.tmp, "claude")
        _write(claude, """#!/usr/bin/env bash
in_variadic=0
prompt_arg=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allowedTools|--allowed-tools|--disallowedTools|--disallowed-tools)
      in_variadic=1; shift ;;
    --model|--permission-mode|--append-system-prompt|--system-prompt|--settings)
      in_variadic=0; shift 2 ;;
    -p|--print) in_variadic=0; shift ;;
    --*) in_variadic=0; shift ;;
    *) if [[ $in_variadic -eq 1 ]]; then shift; else prompt_arg="$1"; shift; fi ;;
  esac
done
stdin_data="$(cat)"
prompt="${stdin_data:-$prompt_arg}"
if [[ -z "$prompt" ]]; then
  echo "Error: Input must be provided either through stdin or as a prompt argument when using --print" >&2
  exit 1
fi
exit 0
""")
        os.chmod(claude, 0o755)
        return claude

    def test_prompt_reaches_agent_via_stdin_not_positional_arg(self):
        claude = self._write_variadic_eating_stub()
        with mock.patch.dict(os.environ, {"CLAUDE_BIN": claude}):
            result = np_agentic_cron.episodic_maintain()
        self.assertEqual(result, "ok: agent run completed",
                          "the agent stub reported no prompt on stdin -- the "
                          "historical variadic-args-eat-the-prompt bug is back")
        # EPISODIC_MAINTAIN_LOG override took effect and the dated run header landed there.
        self.assertTrue(os.path.isfile(self.log))
        with open(self.log, encoding="utf-8") as fh:
            self.assertIn("episodic-maintain run", fh.read())

    def test_regresses_if_prompt_were_lost_to_a_positional_arg(self):
        # Sanity-check the stub itself: force an empty-stdin call directly
        # (bypassing np_llm_agent, which always pipes stdin) to prove the stub
        # DOES fail closed on the historical bug shape, so the pass above is
        # not a tautology.
        claude = self._write_variadic_eating_stub()
        proc = subprocess.run(
            [claude, "-p", "--allowedTools", "Bash", "Read"],
            input="", text=True, capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Input must be provided", proc.stderr)


if __name__ == "__main__":
    unittest.main()
