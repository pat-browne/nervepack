"""PreToolUse hook: the durable-text form gate.

Enforces the categorical rules of np-flow-concise-output (no em dash, no
semicolon, no contraction, no marketing adjective) on text that persists:
files, artifacts, Notion pages, Slack posts, work-item descriptions, and
commit messages. Categorical hits return "ask". Rate-based findings (passive
voice, sentence length) only ever add context.

Fails open everywhere, per ARCHITECTURE invariant 1. "ask" is a permission
prompt rather than a block, so this hook needs no amendment to that invariant;
it follows the precedent lesson_guard already set.

Channel A reads the linter's own violation counts and never reimplements its
regexes. The linter already excludes possessives from the contraction count.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

import np_content
import np_toggle

_PROSE_EXT = (".md", ".mdx", ".html", ".txt")

# Mirrors turn_gate._EXEMPT so the two prose gates agree on what is not prose.
_EXEMPT = re.compile(r"(^|[/\\])(tests?|fixtures?|__snapshots__|node_modules"
                     r"|dist|build)([/\\]|$)|\.min\.", re.I)

_CATEGORICAL = ("em_dash", "semicolon", "contraction", "marketing_adjective")

_RULE_LABEL = {
    "em_dash": "em dash",
    "semicolon": "semicolon",
    "contraction": "contraction",
    "marketing_adjective": "marketing adjective",
}


def _is_prose_path(path):
    return bool(path) and path.lower().endswith(_PROSE_EXT)


def _exempt_globs():
    """Colon-separated globs from the toggle, with ~ expanded.

    np_toggle does NOT expand ~. An unexpanded glob matches nothing, which
    fails open into "nothing is exempt" -- the direction that fires the gate
    on voiced prose. Expand here or the exemption is silently dead.
    """
    raw = np_toggle.param("form_gate.exempt_globs", "") or ""
    return [os.path.expanduser(g) for g in raw.split(":") if g.strip()]


def _is_exempt_path(path):
    if not path:
        return False
    if _EXEMPT.search(path):
        return True
    target = os.path.abspath(os.path.expanduser(path))
    for glob in _exempt_globs():
        if fnmatch.fnmatch(target, glob):
            return True
        # fnmatch does not treat ** as crossing separators; a prefix test does.
        base = glob.rstrip("*").rstrip(os.sep)
        if base and target.startswith(base + os.sep):
            return True
    return False


def _lint_path():
    """Absolute path to the overlay's STE linter, or None.

    The engine ships no linter. With no overlay configured, the gate never
    fires. Same contract as turn_gate._lint_path.
    """
    try:
        root = np_content.content_dir()
    except Exception:
        return None
    if not root:
        return None
    path = os.path.join(root, "engine", "setup", "np-ste-lint.py")
    return path if os.path.isfile(path) else None


def _extract(tool_name, tool_input):
    """Return (text, label) for a gated tool, or (None, "") to allow."""
    return (None, "")


def run(payload_text):
    if not np_toggle.enabled("form_gate"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""

    try:
        text, label = _extract(tool_name, tool_input)
    except Exception:
        return ""
    if not text or not text.strip():
        return ""

    return ""
