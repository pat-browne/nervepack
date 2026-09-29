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
import time
import uuid

import np_bashlib
import np_paths
import np_token_lib
import np_dirs

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


def own_sessions_dir():
    return os.environ.get("NP_OWN_SESSIONS_DIR") or np_dirs.cache_path("own-sessions")


def is_own_session(sid):
    """True iff `sid` names a headless child nervepack itself spawned. The
    back-capture sweep asks this so it stops re-discovering its own `claude -p`
    transcripts as new user sessions to capture (#202)."""
    if not sid:
        return False
    try:
        return os.path.exists(os.path.join(own_sessions_dir(), sid))
    except OSError:
        return False


def _mint_session_id():
    """Name the child session ourselves so it is identifiable later. Recorded
    BEFORE the call, since a call that dies partway still leaves a transcript."""
    sid = str(uuid.uuid4())
    try:
        d = own_sessions_dir()
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, sid), "a").close()
    except OSError:
        pass                                   # fail-open: worst case is a re-discovery
    return sid


def prune_own_sessions(max_age_sec):
    """Drop markers older than the sweep's discovery window -- past it the sweep
    would never look at the transcript again anyway."""
    d = own_sessions_dir()
    cutoff = time.time() - max_age_sec
    try:
        names = os.listdir(d)
    except OSError:
        return
    for name in names:
        path = os.path.join(d, name)
        try:
            if os.stat(path).st_mtime < cutoff:
                os.remove(path)
        except OSError:
            pass


def _claude_bin():
    return os.environ.get("CLAUDE_BIN") or os.path.join(
        os.path.expanduser("~"), ".local", "bin", "claude")


# Built-in tier defaults, used only when no env var or toggle param names a model.
# Opus is selectable in the dashboard but no default uses it (AGENTS.md policy).
DEFAULT_CHEAP = "claude-haiku-4-5-20251001"
DEFAULT_AGENT = "claude-sonnet-5-5"
_TIER_ENV = {"cheap": "NP_LLM_MODEL_CHEAP", "agent": "NP_LLM_MODEL_AGENT"}
_TIER_DEFAULT = {"cheap": DEFAULT_CHEAP, "agent": DEFAULT_AGENT}


def _param(key):
    """models.<key> from the toggle manifest, or "". Fail-open: a broken
    resolver must never stop a model call."""
    try:
        import np_toggle
        return (np_toggle.param("models." + key, "") or "").strip()
    except Exception:
        return ""


def feature_key(feature):
    """Param key for a feature name: `episodic-maintain` -> `episodic_maintain`."""
    return (feature or "").strip().replace("-", "_")


def resolve_model(tier, feature=None):
    """Precedence: tier env var > models.<feature> > models.<tier> > default.
    The env vars win so existing overrides keep working unchanged."""
    env = os.environ.get(_TIER_ENV[tier])
    if env:
        return env
    if feature:
        v = _param(feature_key(feature))
        if v:
            return v
    return _param(tier) or _TIER_DEFAULT[tier]


def _model_cheap(feature=None):
    return resolve_model("cheap", feature)


def _model_agent(feature=None):
    return resolve_model("agent", feature)


# --- model inventory + availability probe ----------------------------------
# The CLI prints this when the account cannot use --model. Exit status and
# stream vary by version, so the text is the signal.
_MODEL_ERROR_RE = None


def model_error_line(text):
    """The CLI's "issue with the selected model" line in `text`, else ""."""
    global _MODEL_ERROR_RE
    if _MODEL_ERROR_RE is None:
        import re
        _MODEL_ERROR_RE = re.compile(r"[^\n]*issue with the selected model[^\n]*", re.I)
    m = _MODEL_ERROR_RE.search(text or "")
    return m.group(0).strip()[:300] if m else ""


def inventory_path():
    return os.environ.get("NP_MODEL_INVENTORY") or os.path.join(np_paths.SETUP_DIR, "model-inventory.json")


def inventory():
    """Curated known model ids: list of {id, tier, label, legacy}. [] on error."""
    import json
    try:
        with open(inventory_path(), encoding="utf-8") as fh:
            return list(json.load(fh).get("models") or [])
    except (OSError, ValueError):
        return []


def probe_cache_path():
    return os.environ.get("NP_MODEL_PROBE_CACHE") or np_dirs.cache_path("model-probe.json")


def load_probe_cache():
    import json
    try:
        with open(probe_cache_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_probe(model, status, reason=""):
    """Store one probe result {status, reason, ts}. Fail-open."""
    import json
    if not model:
        return
    data = load_probe_cache()
    data[model] = {"status": status, "reason": reason[:300],
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    path = probe_cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


def classify_probe(returncode, out, err):
    """(status, reason) for one probe run: available | missing | error."""
    text = (out or "") + "\n" + (err or "")
    line = model_error_line(text)
    if line:
        return "missing", line
    try:
        check_auth(out)
    except AuthError as exc:
        return "error", "auth: %s" % exc
    if returncode != 0:
        tail = (err or out or "").strip().splitlines()
        return "error", ("exit %s: %s" % (returncode, tail[-1] if tail else ""))[:300]
    return "available", ""


def probe(model, timeout=60):
    """Run a 1-token prompt against `model` via the claude CLI and cache the
    verdict. Returns {status, reason}. Only the claude backend is probed."""
    backend = os.environ.get("NP_LLM_BACKEND") or "claude"
    if backend != "claude":
        status, reason = "error", "probe needs the claude backend (have %s)" % backend
    else:
        argv = [_claude_bin(), "-p", "--session-id", _mint_session_id(),
                "--model", model, "--allowedTools", ""]
        try:
            r = np_bashlib.run_killtree(np_bashlib.argv(argv), input="Reply with: ok",
                                        env=_base_env(backend), timeout=timeout)
            status, reason = classify_probe(r.returncode, r.stdout, r.stderr)
        except Exception as exc:               # timeout, missing binary
            status, reason = "error", "%s: %s" % (type(exc).__name__, exc)
    record_probe(model, status, reason)
    return {"status": status, "reason": reason}


def _note_model_error(model, *texts):
    """Mark `model` missing in the probe cache when the CLI rejected it."""
    line = model_error_line("\n".join(t or "" for t in texts))
    if line:
        record_probe(model, "missing", line)
    return line


def _claude_token():
    """The long-lived `claude setup-token` OAuth token, read from the file the
    scheduled-auth installer writes. Returns None when there isn't a usable one.

    The CLI's own interactive credentials expire independently of this token, so
    without the fallback below a machine with a valid token file still failed
    every NON-cron model call ("OAuth session expired and could not be
    refreshed") while the doctor's `scheduled-auth-token` check reported PASS --
    the scheduler installers were the only thing injecting it, via
    np_token_lib.claude_token_env_prefix's shell snippet. Read at CALL time, not
    import time, so rotating the token is still just overwriting the file."""
    try:
        with open(np_token_lib.claude_token_file()) as fh:
            return fh.read().strip() or None
    except OSError:
        return None                            # absent/unreadable -> no token, not a crash


def _base_env(backend="claude"):
    """Env for every backend call: NERVEPACK_AGENT=1 (the SessionEnd-recursion
    guard the retired np-llm.sh centralized), the CLAUDE_CODE_* strip above, and
    -- for the `claude` backend only -- the scheduled-auth token fallback. The
    `local` backend talks to a non-Anthropic endpoint, so handing it the token
    would leak a credential to a process with no use for it."""
    env = dict(os.environ)
    env["NERVEPACK_AGENT"] = "1"
    for v in _STRIP_ENV_VARS:
        env.pop(v, None)
    if backend == "claude" and not env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        token = _claude_token()                # an exported token wins: caller is authority
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def complete(prompt, system=None, timeout=None, feature=None):
    """Run a single-shot completion; return the backend's stdout (unstripped, as
    the retired np-llm.sh did). Covers `complete` for both backends. `timeout`
    (seconds, None = no limit) lets a long-lived caller
    (e.g. the dashboard server) bound the call; raises subprocess.TimeoutExpired
    like any subprocess.run timeout would. `feature` picks a per-feature model
    param (models.<feature>) before the cheap tier."""
    backend = os.environ.get("NP_LLM_BACKEND") or "claude"
    env = _base_env(backend)
    model = _model_cheap(feature)
    if backend == "claude":
        argv = [_claude_bin(), "-p", "--session-id", _mint_session_id(),
                "--model", model, "--allowedTools", ""]
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
    if backend == "claude":
        _note_model_error(model, r.stdout, r.stderr)
    return r.stdout


def agent(prompt, tools, cwd=None, timeout=None, feature=None):
    """Run an agentic task (file edits, commits): tools-enabled, permissions
    bypassed, agent-tier model. Covers `agent` for both backends.
    Returns (returncode, stdout, stderr) -- callers need the exit code
    (np_llm_agent.run_agent()'s pass/fail contract), unlike complete(). `timeout`
    (seconds, None = no limit) lets a caller (np_implement_suggestion.py) bound
    a hung agent; raises subprocess.TimeoutExpired on expiry, same as any
    subprocess.run timeout would -- callers decide how to fail open."""
    backend = os.environ.get("NP_LLM_BACKEND") or "claude"
    env = _base_env(backend)
    model = _model_agent(feature)
    if backend == "claude":
        # --allowedTools is variadic (consumes space-separated tokens until the
        # next flag) -- tools.split() mirrors bash's unquoted `$tools` word-split.
        argv = [_claude_bin(), "-p", "--session-id", _mint_session_id(),
                "--settings", '{"hooks":{},"includeCoAuthoredBy":false}',
                "--permission-mode", "bypassPermissions",
                "--model", model, "--allowedTools"] + tools.split()
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
    if backend == "claude":
        _note_model_error(model, r.stdout, r.stderr)
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
