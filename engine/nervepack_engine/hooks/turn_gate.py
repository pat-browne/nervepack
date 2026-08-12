"""Stop hook: the turn-completion gate.

Blocks a turn ONCE when it edited UI files and never showed the result. This is
the single hook in nervepack permitted to block, per the amended ARCHITECTURE
invariant 1. Every one of its own error paths still returns "" and allows.

Order matters: stop_hook_active is checked before any parsing, toggle read, or
file access. The harness caps consecutive blocks at 8, but this gate must never
depend on that backstop.
"""
import json
import os
import re

import np_toggle
import np_turn_parse

_UI_EXT = (".html", ".css", ".scss", ".sass", ".less", ".jsx", ".tsx",
           ".vue", ".svelte", ".astro", ".dart")
_EXEMPT = re.compile(r"(^|[/\\])(tests?|fixtures?|__snapshots__|node_modules|dist|build)"
                     r"([/\\]|$)|\.min\.", re.I)

_LADDER = ("Serve it and open it in the browser, or take a screenshot and show it. "
           "If the change has no visual surface (a refactor, a comment, a build "
           "tweak), say so plainly and finish -- that is a valid resolution and "
           "this gate will not ask twice.")


def _is_ui(path):
    return path.lower().endswith(_UI_EXT) and not _EXEMPT.search(path)


def _mode(param, default):
    value = (np_toggle.param(param, default) or default).strip().lower()
    return value if value in ("block", "warn", "off") else default


def _block(reason):
    return json.dumps({"decision": "block", "reason": reason})


def _warn(text):
    return json.dumps({"hookSpecificOutput": {"hookEventName": "Stop",
                                              "additionalContext": text}})


def run(payload_text, *_args):
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""

    # Loop guard FIRST. Nothing above this line may read a file or a toggle.
    if payload.get("stop_hook_active"):
        return ""

    if not np_toggle.enabled("turn_gate"):
        return ""

    try:
        turn = np_turn_parse.parse(payload.get("transcript_path") or "")
    except Exception:
        return ""

    ui_mode = _mode("turn_gate.ui", "block")
    if ui_mode == "off":
        return ""

    ui_files = [p for p in turn.edits if _is_ui(p)]
    if not ui_files or turn.delivery:
        return ""

    names = ", ".join(sorted({os.path.basename(p) for p in ui_files})[:5])
    message = ("This turn edited %s but never showed the result. %s"
               % (names, _LADDER))
    return _block(message) if ui_mode == "block" else _warn(message)
