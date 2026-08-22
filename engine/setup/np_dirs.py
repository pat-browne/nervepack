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

## A relative XDG value is IGNORED, and reported

The XDG spec is explicit: a relative value is invalid and "should be considered
invalid and ignored". This module does exactly that, falling back to the default,
and records it so the doctor can report it.

An earlier draft raised instead, following Go's stdlib. That was wrong for THIS
codebase: `np_toggle` resolves through here, sixteen hook modules read toggles,
and hooks fail open by ARCHITECTURE invariant 1. Raising would therefore have
made one bad environment variable silently disable the entire session lifecycle
-- no error, nothing red, the exact silent-total-failure shape #295 removed from
hook registration.

Ignoring keeps every hook working. Reporting keeps the mistake visible. Raising
achieved neither.

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
# The historical locations, and still the defaults. Exported so the doctor can
# say when a resolution landed somewhere else without re-deriving the rule.
DEFAULT_CACHE_REL = ".cache"
DEFAULT_CONFIG_REL = ".config"

# The reason a marker exists rather than a log line: this resolves inside hooks,
# which must not write to the session's streams. The doctor reads it to answer
# "why is my XDG_CACHE_HOME being ignored" without anyone reading source.
_legacy_wins = set()


# Set to something that cannot be a base directory. Reported, never raised: see
# the module docstring on why raising here would disable the session lifecycle.
_invalid = {}


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _resolve(env_var, default_rel):
    base = os.environ.get(env_var)
    legacy = os.path.join(_home(), default_rel, APP)
    # Clear both markers ONCE, here, before any branch decides anything. Each
    # branch below then only ever ADDS. Clearing per-branch is how this module
    # shipped a stale marker twice -- a new branch simply forgot one -- and
    # making that structurally impossible is worth more than the two lines.
    _legacy_wins.discard(env_var)
    _invalid.pop(env_var, None)
    if not base:
        return legacy
    if not os.path.isabs(base):
        # Ignored per the XDG spec, and recorded so the doctor can say so. A
        # relative value would anchor state to whatever directory a hook started
        # in, which is why it cannot simply be normalised.
        _invalid[env_var] = base
        return legacy
    derived = os.path.join(base, APP)
    # Legacy precedence, deliberately: see the module docstring.
    if os.path.isdir(legacy) and not os.path.isdir(derived):
        _legacy_wins.add(env_var)
        return legacy
    return derived


def cache_dir():
    """Per-machine cache: queues, logs, resume state. `XDG_CACHE_HOME`."""
    return _resolve("XDG_CACHE_HOME", DEFAULT_CACHE_REL)


def config_dir():
    """Per-machine config: toggles, layer pointers, the OAuth token.
    `XDG_CONFIG_HOME`."""
    return _resolve("XDG_CONFIG_HOME", DEFAULT_CONFIG_REL)


def cache_path(*parts):
    """A path under cache_dir(). Nothing is created."""
    return os.path.join(cache_dir(), *parts)


def config_path(*parts):
    """A path under config_dir(). Nothing is created."""
    return os.path.join(config_dir(), *parts)


def invalid_values():
    """{variable: value} for XDG variables set to something unusable, currently.
    Empty unless a resolution actually hit one, so the doctor reports it only
    when it is true right now."""
    return dict(_invalid)


def legacy_overrides():
    """Which XDG variables are set but being ignored in favour of a legacy
    directory. Empty unless a resolution actually took that branch, so the
    doctor reports it only when it is true right now."""
    return sorted(_legacy_wins)
