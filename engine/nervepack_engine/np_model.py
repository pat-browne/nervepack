"""Bash-free model-completion + agent seam -- the SOLE runtime model seam
(both `complete` and `agent` modes). The `claude` CLI and the `local` backend's
`np-llm-local.py` (`complete` mode) both run natively (no bash); `agent`
mode's `local` backend still shells `NP_LLM_AGENT_CMD` via `bash -c` (that's
an arbitrary user-supplied shell command, not something to natively
reimplement), routed through np_bashlib.argv() for the right interpreter on
Windows.

History: the git-for-windows-free MCP work (#38) ported `complete` in-process,
phase 9 ported `agent` (np_llm_agent.py's run_agent() calls agent() here
directly), and phase 19 retired the old bash wrapper `np-llm.sh` entirely --
nothing shells it any more; this module is the single seam every model call
routes through. The backend argv/env contract (argv shape, NERVEPACK_AGENT=1
recursion guard, CLAUDE_CODE_* strip, prompt on stdin, both backends/both
modes) that the wrapper's black-box test pinned is now held host-agnostically
by tests/llm/test_np_model_contract.py. stdlib only.
"""
import os
import sys
# self-bootstrap (phase 20b-2): engine/setup holds np_paths, np_bashlib, the config
# files, and the stayed sibling modules; add it so this relocated module resolves them
# whether imported in-process or run standalone. Its own dir (nervepack_engine) is
# already on sys.path[0] when run directly, so moved-sibling imports resolve too.
_SETUP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import os
import sys

import np_bashlib
import np_paths

# Long-lived nervepack processes (the dashboard server, backgrounded SessionStart
# hooks) are spawned from inside an interactive Claude Code session and inherit its
# CLAUDECODE/CLAUDE_CODE_* env vars for their whole lifetime -- including a
# CLAUDE_CODE_SESSION_ID for a session that has since ended. A nested `claude -p`
# call that inherits those vars can be mistaken for a child of that (possibly stale)
# session rather than an independent headless run, surfacing as a spurious "Not
# logged in · Please run /login" (found 2026-07-13, in the retired np-llm.sh). Strip them so every
# nervepack `claude` invocation authenticates as its own top-level headless call.
_STRIP_ENV_VARS = (
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_SSE_PORT",
)


class AuthError(RuntimeError):
    """The backend could not authenticate. Its own type because the CLI reports
    this on stdout with exit 0, so callers that fail open on a generic failure
    would otherwise read it as a benign empty result (#201, #211)."""


# The CLI emits one of these as the whole of stdout when auth fails. Matched
# against the first line only -- a legitimate response may quote the text.
_AUTH_SIGNATURES = (
    "failed to authenticate",
    "not logged in",
    "oauth session expired",
    "invalid api key",
)


def check_auth(text):
    if not text:
        return
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if any(low.startswith(sig) for sig in _AUTH_SIGNATURES):
            raise AuthError(line)
        return                                     # only the first line counts


def _claude_bin():
    return os.environ.get("CLAUDE_BIN") or os.path.join(
        os.path.expanduser("~"), ".local", "bin", "claude")


def _model_cheap():
    return os.environ.get("NP_LLM_MODEL_CHEAP") or "claude-haiku-4-5-20251001"


def _model_agent():
    return os.environ.get("NP_LLM_MODEL_AGENT") or "claude-sonnet-4-6"


def _base_env():
    """Env for every backend call: NERVEPACK_AGENT=1 (the SessionEnd-recursion
    guard the retired np-llm.sh centralized) plus the CLAUDE_CODE_* strip above."""
    env = dict(os.environ)
    env["NERVEPACK_AGENT"] = "1"
    for v in _STRIP_ENV_VARS:
        env.pop(v, None)
    return env


def complete(prompt, system=None, timeout=None):
    """Run a single-shot completion; return the backend's stdout (unstripped, as
    the retired np-llm.sh did). Covers `complete` for both backends. `timeout`
    (seconds, None = no limit) lets a long-lived caller
    (e.g. the dashboard server) bound the call; raises subprocess.TimeoutExpired
    like any subprocess.run timeout would."""
    backend = os.environ.get("NP_LLM_BACKEND") or "claude"
    env = _base_env()
    if backend == "claude":
        argv = [_claude_bin(), "-p", "--model", _model_cheap(), "--allowedTools", ""]
        if system:
            argv += ["--append-system-prompt", system]
    elif backend == "local":
        argv = [sys.executable, os.path.join(np_paths.SETUP_DIR, "np-llm-local.py"), "complete"]
        if system:
            argv += ["--system", system]
    else:
        raise ValueError("np_model: backend %r not implemented (only claude/local)" % backend)
    # run_killtree, not subprocess.run: on a timeout, plain subprocess.run's own
    # Windows kill-then-drain fallback can block forever if a grandchild the
    # backend spawned is still holding the output pipe open -- see
    # np_bashlib.run_killtree's docstring (confirmed via CPython's own
    # subprocess.run source, not a guess).
    r = np_bashlib.run_killtree(np_bashlib.argv(argv), input=prompt, env=env, timeout=timeout)
    check_auth(r.stdout)
    return r.stdout


def agent(prompt, tools, cwd=None, timeout=None):
    """Run an agentic task (file edits, commits): tools-enabled, permissions
    bypassed, agent-tier model. Covers `agent` for both backends.
    Returns (returncode, stdout, stderr) -- callers need the exit code
    (np_llm_agent.run_agent()'s pass/fail contract), unlike complete(). `timeout`
    (seconds, None = no limit) lets a caller (np_implement_suggestion.py) bound
    a hung agent; raises subprocess.TimeoutExpired on expiry, same as any
    subprocess.run timeout would -- callers decide how to fail open."""
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
    # run_killtree, not subprocess.run -- see complete()'s comment above; the
    # agent backend is even more exposed since it's tools-enabled and can
    # itself spawn arbitrary child processes (git, a local agentic host).
    r = np_bashlib.run_killtree(np_bashlib.argv(argv), input=prompt, cwd=cwd, env=env, timeout=timeout)
    check_auth(r.stdout)
    return r.returncode, r.stdout, r.stderr


if __name__ == "__main__":
    # CLI entrypoint (the interface the retired np-llm.sh exposed): prompt on
    # stdin, output on stdout.
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
