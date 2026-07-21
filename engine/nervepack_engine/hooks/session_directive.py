"""Bash-free port of nervepack-session-directive.sh -- the synchronous SessionStart
hook that injects the "consult nervepack first" directive as additionalContext.
Byte-stable (invariant 11): no timestamps/volatile fields, so the composed output
forms a cache-stable KV-cache prefix; all variable, session-specific context is
injected LATER via UserPromptSubmit recall hooks, never interleaved here.

Content-fed routing fragments (directive-routing.md) are appended from every merge
root (team[0..n] > personal, highest-precedence first) via np_content.merge_roots()
-- the in-process Python mirror of np-layer-lib.sh's np_merge_roots, already used by
lesson_recall.py/episodic_recall.py for the same purpose. Fail-open throughout: a
disabled toggle, missing directive markdown, or a missing/errored merge root yields
either "" or a narrower (but still valid) composed result -- never an exception.

Unlike every other hook ported so far, this one reads nothing from its stdin
payload -- it is driven entirely by toggle state, the committed directive
markdown, and content-overlay merge roots, exactly like its bash original.
"""
import json
import os

import np_content
import np_toggle

_ENGINE_SETUP_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "setup"))
_DIRECTIVE_PATH = os.path.join(_ENGINE_SETUP_DIR, "nervepack-session-directive.md")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def run(payload_text):
    if not np_toggle.enabled("directive"):
        return ""
    content = _read(_DIRECTIVE_PATH)
    if content is None:
        return ""

    try:
        roots = np_content.merge_roots()
    except Exception:
        roots = []
    for root in roots:
        frag = _read(os.path.join(root, "directive-routing.md"))
        if frag is not None:
            content += frag

    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": content}},
        separators=(",", ":"))
