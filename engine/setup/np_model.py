"""Bash-free model-completion + agent seam — the in-process equivalent of
`np-llm.sh` (both `complete` and, as of phase 9 of the bash->Python CLI
consolidation, `agent` mode). The `claude` CLI and the `local` backend's
`np-llm-local.py`/`NP_LLM_AGENT_CMD` both run natively (no bash). Slice 4
(step 2) of the git-for-windows-free MCP work (#38) ported `complete`;
phase 9 (content overlay spec
2026-07-15-nervepack-python-cli-consolidation-design.md) ports `agent` --
np_llm_agent.py's run_agent() now calls agent() here directly instead of
shelling to bash `np-llm.sh agent`. np-llm.sh itself stays on disk (bash)
until phase 10 ports its last remaining direct caller,
np-implement-suggestion.sh.

Parity-locked to np-llm.sh (same argv + stdin, both modes) by
tests/mcp/parity/test_model_parity.sh and test_agent_parity.sh. stdlib only.
"""
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Long-lived nervepack processes (the dashboard server, backgrounded SessionStart
# hooks) are spawned from inside an interactive Claude Code session and inherit its
# CLAUDECODE/CLAUDE_CODE_* env vars for their whole lifetime -- including a
# CLAUDE_CODE_SESSION_ID for a session that has since ended. A nested `claude -p`
# call that inherits those vars can be mistaken for a child of that (possibly stale)
# session rather than an independent headless run, surfacing as a spurious "Not
# logged in · Please run /login" (found 2026-07-13, np-llm.sh). Strip them so every
# nervepack `claude` invocation authenticates as its own top-level headless call.
_STRIP_ENV_VARS = (
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_SSE_PORT",
)


def _claude_bin():
    return os.environ.get("CLAUDE_BIN") or os.path.join(
        os.path.expanduser("~"), ".local", "bin", "claude")


def _model_cheap():
    return os.environ.get("NP_LLM_MODEL_CHEAP") or "claude-haiku-4-5-20251001"


def _model_agent():
    return os.environ.get("NP_LLM_MODEL_AGENT") or "claude-sonnet-4-6"


def _base_env():
    """Env for every backend call: NERVEPACK_AGENT=1 (the SessionEnd-recursion
    guard np-llm.sh sets) plus the CLAUDE_CODE_* strip above."""
    env = dict(os.environ)
    env["NERVEPACK_AGENT"] = "1"
    for v in _STRIP_ENV_VARS:
        env.pop(v, None)
    return env


def complete(prompt, system=None, timeout=None):
    """Run a single-shot completion; return the backend's stdout (unstripped, as
    np-llm.sh does). Mirrors np-llm.sh `complete` for both backends. `timeout`
    (seconds, None = no limit, matching np-llm.sh) lets a long-lived caller
    (e.g. the dashboard server) bound the call; raises subprocess.TimeoutExpired
    like any subprocess.run timeout would."""
    backend = os.environ.get("NP_LLM_BACKEND") or "claude"
    env = _base_env()
    if backend == "claude":
        argv = [_claude_bin(), "-p", "--model", _model_cheap(), "--allowedTools", ""]
        if system:
            argv += ["--append-system-prompt", system]
    elif backend == "local":
        argv = [sys.executable, os.path.join(_HERE, "np-llm-local.py"), "complete"]
        if system:
            argv += ["--system", system]
    else:
        raise ValueError("np_model: backend %r not implemented (only claude/local)" % backend)
    r = subprocess.run(argv, input=prompt, capture_output=True, text=True, env=env, timeout=timeout)
    return r.stdout


def agent(prompt, tools, cwd=None):
    """Run an agentic task (file edits, commits): tools-enabled, permissions
    bypassed, agent-tier model. Mirrors np-llm.sh `agent` for both backends.
    Returns (returncode, stdout, stderr) -- callers need the exit code
    (np_llm_agent.run_agent()'s pass/fail contract), unlike complete()."""
    backend = os.environ.get("NP_LLM_BACKEND") or "claude"
    env = _base_env()
    if backend == "claude":
        # --allowedTools is variadic (consumes space-separated tokens until the
        # next flag) -- tools.split() mirrors bash's unquoted `$tools` word-split.
        argv = [_claude_bin(), "-p",
                "--settings", '{"hooks":{},"includeCoAuthoredBy":false}',
                "--permission-mode", "bypassPermissions",
                "--model", _model_agent(), "--allowedTools"] + tools.split()
    elif backend == "local":
        agent_cmd = os.environ.get("NP_LLM_AGENT_CMD")
        if not agent_cmd:
            return (2, "", "np-llm: agent mode needs NP_LLM_AGENT_CMD "
                            "(an agentic host, e.g. goose); see onboard\n")
        argv = ["bash", "-c", agent_cmd]
        env["NP_LLM_TOOLS"] = tools
    else:
        raise ValueError("np_model: backend %r not implemented (only claude/local)" % backend)
    r = subprocess.run(argv, input=prompt, cwd=cwd, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


if __name__ == "__main__":
    # CLI mirror of np-llm.sh: prompt on stdin, output on stdout.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    argv = sys.argv[1:]
    if argv and argv[0] == "complete":
        rest = argv[1:]
        system = None
        if "--system" in rest:
            i = rest.index("--system")
            system = rest[i + 1] if i + 1 < len(rest) else ""
        sys.stdout.write(complete(sys.stdin.read(), system))
    elif argv and argv[0] == "agent":
        rest = argv[1:]
        tools = ""
        if "--tools" in rest:
            i = rest.index("--tools")
            tools = rest[i + 1] if i + 1 < len(rest) else ""
        rc, out, err = agent(sys.stdin.read(), tools)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    else:
        sys.stderr.write("usage: np_model.py complete [--system S] | agent --tools \"T...\"  (prompt on stdin)\n")
        sys.exit(2)
