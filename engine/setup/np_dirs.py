#!/usr/bin/env python3
"""Where nervepack keeps its per-machine state (F11/#299).

Two questions, one answer each, in one place. Before this, 51 call sites across
~28 files built `~/.cache/nervepack/...` and `~/.config/nervepack/...` inline,
and no `XDG_*` variable was read anywhere -- a machine that set `XDG_CACHE_HOME`
was silently ignored.

What lives here is why this is careful rather than clever:

    config_dir()   toggles.local, content-dir, team-dir, adapter.json,
                   claude-oauth-token, layouts/
    cache_dir()    episodic-inbox, evaluator-inbox, session-signals,
                   backcapture-{seen,queue}, resume state, every hook log

A real credential and the memory pipeline's queues.

## Legacy wins when it already exists

If `~/.cache/nervepack` is present and the XDG-derived directory is not, the
legacy path is used. This is git's own precedence -- `~/.gitconfig` takes
precedence over `$XDG_CONFIG_HOME/git/config` -- and it is the only rule under
which an existing install cannot silently orphan its state the day someone
exports `XDG_CACHE_HOME` for an unrelated program.

The cost is real: someone who sets `XDG_CACHE_HOME` INTENDING to relocate an
existing install will not be relocated. That is the safer surprise, because it
is visible (the state is where it always was) rather than invisible (the state
is gone and the pipeline restarts empty).

## A relative XDG value is an error, not a path

The XDG spec says a relative value is invalid and must be ignored. Normalising
it silently would anchor nervepack's state to the process's working directory --
and these run from hooks, which start in whatever project the user happened to
open. That is the worst available outcome, so it raises.

## macOS

`XDG_*` is honoured on every platform including macOS, following platformdirs;
Go's `os.UserConfigDir` ignores it on Darwin and returns
`~/Library/Application Support`. There is no agreed answer. Honouring it keeps
macOS byte-identical to nervepack's current behaviour, which is what an existing
install needs. See docs/XDG-DIRECTORIES.md.

This module creates nothing. Callers that write already create their own
directories, and a resolver with a side effect cannot be asked a question.

Pure stdlib.
"""
import os

APP = "nervepack"

# The reason a marker exists rather than a log line: this resolves inside hooks,
# which must not write to the session's streams. The doctor reads it to answer
# "why is my XDG_CACHE_HOME being ignored" without anyone reading source.
_legacy_wins = set()


class DirectoryError(Exception):
    """An XDG variable is set to something that cannot be a base directory."""


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _resolve(env_var, default_rel):
    base = os.environ.get(env_var)
    legacy = os.path.join(_home(), default_rel, APP)
    if not base:
        # Clear any earlier override before returning. A long-lived process --
        # the dashboard server, the MCP server -- can resolve more than once,
        # and a stale entry would make legacy_overrides() report a variable that
        # is no longer set at all.
        _legacy_wins.discard(env_var)
        return legacy
    if not os.path.isabs(base):
        raise DirectoryError(
            "%s is %r, which is relative. The XDG spec requires an absolute "
            "path, and a relative one would anchor nervepack's state to "
            "whatever directory a hook happened to start in." % (env_var, base))
    derived = os.path.join(base, APP)
    # Legacy precedence, deliberately: see the module docstring.
    if os.path.isdir(legacy) and not os.path.isdir(derived):
        _legacy_wins.add(env_var)
        return legacy
    _legacy_wins.discard(env_var)
    return derived


def cache_dir():
    """Per-machine cache: queues, logs, resume state. `XDG_CACHE_HOME`."""
    return _resolve("XDG_CACHE_HOME", ".cache")


def config_dir():
    """Per-machine config: toggles, layer pointers, the OAuth token.
    `XDG_CONFIG_HOME`."""
    return _resolve("XDG_CONFIG_HOME", ".config")


def cache_path(*parts):
    """A path under cache_dir(). Nothing is created."""
    return os.path.join(cache_dir(), *parts)


def config_path(*parts):
    """A path under config_dir(). Nothing is created."""
    return os.path.join(config_dir(), *parts)


def legacy_overrides():
    """Which XDG variables are set but being ignored in favour of a legacy
    directory. Empty unless a resolution actually took that branch, so the
    doctor reports it only when it is true right now."""
    return sorted(_legacy_wins)
