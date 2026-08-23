#!/usr/bin/env python3
"""Where the HOST keeps things (F11/#300).

Three questions, one answer each. Distinct from np_dirs, which answers where
NERVEPACK keeps its own state: this module is about the agentic host's files --
its settings, its skill directory, its transcripts.

Before this, the same resolution was written out repeatedly:

    CLAUDE_SETTINGS or ~/.claude/settings.json   five copies
    NP_SKILLS_DST   or ~/.claude/skills          one
    CLAUDE_PROJECTS_DIR or ~/.claude/projects    three

Five copies of one decision means a host whose settings live elsewhere has to be
taught in five places, and a sixth copy is one commit away.

## Resolution order, and why

    1. the existing environment variable
    2. a `paths` entry in ~/.config/nervepack/adapter.json
    3. today's ~/.claude/... default

The environment keeps winning because it already did. `capabilities.json` tells
a non-Claude host to set `CLAUDE_SETTINGS`, and an adapter manifest is a
per-machine file written once at onboarding -- so the variable is what someone
reaches for when the manifest is wrong. A manifest that could not be overridden
would be worse than no manifest.

## The adapter gains an optional block

    "paths": {
      "settings":    "~/.claude/settings.json",
      "skills_dir":  "~/.claude/skills",
      "transcripts": "~/.claude/projects"
    }

Optional in full AND in part: an adapter with no `paths`, or with only one of
the three, behaves exactly as today for whatever it omits. Every manifest on
disk right now has none, and this must not require rewriting one.

A relative value is ignored, like np_dirs and for the same reason -- these
resolve inside hooks that start in whatever directory the user opened. The
adapter is per-machine and hand-written, so `~` IS expanded.

This module creates nothing.

Pure stdlib.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import np_dirs  # noqa: E402  -- same directory; needed for the adapter path

# Set to something unusable in the manifest. Reported, never raised: np_hook and
# the recall hooks resolve through here, and hooks fail open, so raising would
# turn one bad manifest key into a silently dead lifecycle (see np_dirs).
_invalid = {}
# The adapter exists and could not be used. Distinct from absent, which is the
# ordinary state on a machine that never onboarded a non-default host.
_unreadable = {}

_DEFAULTS = {
    "settings": (".claude", "settings.json"),
    "skills_dir": (".claude", "skills"),
    "transcripts": (".claude", "projects"),
}
_ENV = {
    "settings": "CLAUDE_SETTINGS",
    "skills_dir": "NP_SKILLS_DST",
    "transcripts": "CLAUDE_PROJECTS_DIR",
}


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _expanduser(value):
    """Expand a leading `~` against the SAME home the defaults use.

    Not os.path.expanduser: on Windows it prefers USERPROFILE while `_home()`
    prefers $HOME, so a manifest saying "~/x" would resolve against a different
    directory than the built-in default beside it -- inconsistent inside one
    module. That divergence is exactly what #302 removed from two hooks, and it
    came straight back here.

    The result is normpath'ed because a manifest is hand-written and will use
    forward slashes: joining "elsewhere/skills" onto a Windows home produced
    `C:\\...\\elsewhere/skills`, which the OS accepts and every string comparison
    does not. This is S1075's often-missed sub-rule -- do not hardcode the
    separator -- applied to a value that arrives from outside.

    Only manifest values are normalised. An environment variable is the user's
    explicit, current instruction and is used verbatim.
    """
    if value == "~":
        return _home()
    if value.startswith("~/") or value.startswith("~\\"):
        return os.path.normpath(os.path.join(_home(), value[2:]))
    return os.path.normpath(value)


def _adapter_paths():
    """The manifest's `paths` block, or {} for any reason at all.

    A missing, unreadable or malformed adapter is not an error here: the doctor
    already reports a broken manifest through its own check, and this resolver
    falling back to the defaults keeps every hook working while that gets fixed.
    """
    path = os.environ.get("NP_ADAPTER") or np_dirs.config_path("adapter.json")
    _unreadable.pop("adapter", None)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        # Absent is the normal case: most machines have no adapter at all.
        return {}
    except (OSError, ValueError) as exc:
        # PRESENT but unusable -- a permission error or malformed JSON. Recorded
        # separately from "not found", because "your adapter is being ignored"
        # and "you have no adapter" need different answers from the doctor.
        _unreadable["adapter"] = "%s: %s" % (path, exc)
        return {}
    paths = data.get("paths") if isinstance(data, dict) else None
    return paths if isinstance(paths, dict) else {}


def _resolve(key):
    # Cleared ONCE, before any branch decides anything; every branch below only
    # ever ADDS. This is the shape np_dirs settled on after shipping a stale
    # marker twice -- a branch that forgets to clear cannot exist if there is
    # nothing to forget. It did not carry over to this module on the first pass.
    _invalid.pop(key, None)

    env = os.environ.get(_ENV[key])
    if env:
        return env

    declared = _adapter_paths().get(key)
    if isinstance(declared, str) and declared.strip():
        expanded = _expanduser(declared.strip())
        if os.path.isabs(expanded):
            return expanded
        # Ignored, and recorded so the doctor can say so. A relative value would
        # anchor the host's files to whatever directory a hook started in.
        _invalid[key] = declared

    return os.path.join(_home(), *_DEFAULTS[key])


def settings_path():
    """The host's hook/settings file. `CLAUDE_SETTINGS` overrides."""
    return _resolve("settings")


def skills_dir():
    """Where the host reads skills from. `NP_SKILLS_DST` overrides."""
    return _resolve("skills_dir")


def transcripts_dir():
    """Where the host writes session transcripts. `CLAUDE_PROJECTS_DIR`
    overrides."""
    return _resolve("transcripts")


def default_for(key):
    """Today's built-in answer, so a caller can tell whether resolution moved."""
    return os.path.join(_home(), *_DEFAULTS[key])


def invalid_values():
    """{key: value} for `paths` entries that could not be used.

    EPHEMERAL: this reflects the last resolution of each key, not a history. A
    key is cleared the moment it resolves cleanly, so a caller that wants a true
    answer must resolve first and read second -- which is what the doctor does.
    Empty on a machine with no adapter, or one whose `paths` are all usable.
    """
    return dict(_invalid)


def unreadable_adapter():
    """The adapter file exists and could not be parsed, or "" if it is fine.

    Distinct from absent on purpose: "you have no adapter" and "your adapter is
    being ignored" need different answers, and both resolve to the defaults.
    """
    return _unreadable.get("adapter", "")
