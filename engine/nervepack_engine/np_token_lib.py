"""Python port of the pieces of np-token-lib.sh nervepack's Python callers need:
np_claude_token_env_prefix (the scheduler installers) and np_claude_token_status
(the phase-15 in-process doctor). store() stays bash-only (np-token-lib.sh) --
62-install-scheduled-auth-token.sh still sources the bash original to mint the
token, so np-token-lib.sh can't be retired yet.
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
import shlex

import np_token_status


def claude_token_file():
    override = os.environ.get("NP_CLAUDE_TOKEN_FILE")
    if override:
        return override
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".config", "nervepack", "claude-oauth-token")


def claude_token_env_prefix():
    """Shell snippet to PREPEND to a scheduled job's command: re-reads the token
    file at RUN TIME (never baked in at install time), so rotating the token later
    is just overwriting the file -- no reinstall of any scheduled job needed.
    Behaviorally equivalent to np-token-lib.sh's np_claude_token_env_prefix
    (shlex.quote in place of bash's printf %q) -- not byte-identical (the two
    quote styles differ, e.g. shlex.quote single-quotes a space where %q
    backslash-escapes it), but eval'ing either snippet exports the same token
    from the same file. See TestTokenLibParity for the behavioral check."""
    f = claude_token_file()
    return 'f=%s; [ -r "$f" ] && export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$f")"; ' % shlex.quote(f)


def claude_token_status():
    """Port of np-token-lib.sh's np_claude_token_status: the rotation-status word
    for the scheduled-auth token file. Returns exactly one of
    "missing" | "ok <days_left>" | "warn <days_left>" (see np_token_status.py).
    Bash-free -- calls np_token_status.status() in-process rather than
    subprocessing np_token_status.py, so the phase-15 doctor needs no interpreter
    spawn. Behaviorally identical to the bash `python3 np_token_status.py <file>`
    (same default TTL/warn windows)."""
    return np_token_status.status(claude_token_file())
