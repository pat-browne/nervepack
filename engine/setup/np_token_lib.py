"""Python port of the ONE piece of np-token-lib.sh the scheduler installers need:
np_claude_token_env_prefix. store()/status() stay bash-only (np-token-lib.sh) --
62-install-scheduled-auth-token.sh and np-doctor.sh still call the bash original
directly, so it can't be retired yet (phase 8 of the bash->Python migration).
"""
import os
import shlex


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
