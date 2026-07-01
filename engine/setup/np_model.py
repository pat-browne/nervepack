"""Bash-free minimal model-completion seam — the in-process equivalent of
`np-llm.sh complete` (single-shot, cheap model, no tools) used by the ported
capture/evaluate pipelines so they need no bash.

Only `complete` is ported (what capture/evaluate use). `agent` mode (bypass
permissions, tools, or NP_LLM_AGENT_CMD) stays in bash `np-llm.sh` — only the
deferred flush/maintain use it. The `claude` CLI and the `local` backend's
`np-llm-local.py` both run natively (no bash). Slice 4 (step 2) of the
git-for-windows-free MCP work (#38).

Parity-locked to `np-llm.sh complete` (same argv + stdin) by
tests/mcp/parity/test_model_parity.sh. stdlib only.
"""
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _claude_bin():
    return os.environ.get("CLAUDE_BIN") or os.path.join(
        os.path.expanduser("~"), ".local", "bin", "claude")


def _model_cheap():
    return os.environ.get("NP_LLM_MODEL_CHEAP") or "claude-haiku-4-5-20251001"


def complete(prompt, system=None):
    """Run a single-shot completion; return the backend's stdout (unstripped, as
    np-llm.sh does). Mirrors np-llm.sh `complete` for both backends."""
    backend = os.environ.get("NP_LLM_BACKEND") or "claude"
    env = dict(os.environ)
    env["NERVEPACK_AGENT"] = "1"   # the SessionEnd-recursion guard np-llm.sh sets
    if backend == "claude":
        argv = [_claude_bin(), "-p", "--bare", "--model", _model_cheap(), "--allowedTools", ""]
        if system:
            argv += ["--append-system-prompt", system]
    elif backend == "local":
        argv = [sys.executable, os.path.join(_HERE, "np-llm-local.py"), "complete"]
        if system:
            argv += ["--system", system]
    else:
        raise ValueError("np_model: backend %r not implemented (only claude/local)" % backend)
    r = subprocess.run(argv, input=prompt, capture_output=True, text=True, env=env)
    return r.stdout


if __name__ == "__main__":
    # CLI mirror of `np-llm.sh complete`: prompt on stdin, output on stdout.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    argv = sys.argv[1:]
    system = None
    if "--system" in argv:
        i = argv.index("--system")
        system = argv[i + 1] if i + 1 < len(argv) else ""
    if argv and argv[0] == "complete":
        sys.stdout.write(complete(sys.stdin.read(), system))
    else:
        sys.stderr.write("usage: np_model.py complete [--system S]  (prompt on stdin)\n")
        sys.exit(2)
