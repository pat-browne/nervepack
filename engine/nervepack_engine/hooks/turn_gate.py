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
import subprocess
import sys

import np_content
import np_toggle
import np_turn_parse

_UI_EXT = (".html", ".css", ".scss", ".sass", ".less", ".jsx", ".tsx",
           ".vue", ".svelte", ".astro", ".dart")
_EXEMPT = re.compile(r"(^|[/\\])(tests?|fixtures?|__snapshots__|node_modules|dist|build)"
                     r"([/\\]|$)|\.min\.", re.I)
_SPEC_DOC = re.compile(r"[/\\]docs[/\\]superpowers[/\\](?:specs|plans)[/\\]", re.I)

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


def _lint_path():
    """Absolute path to the overlay's STE linter, or None when unavailable.

    The engine deliberately does not ship a linter. When no overlay is
    configured (a fresh forker), the form check simply never fires.
    """
    try:
        root = np_content.content_dir()
    except Exception:
        return None
    if not root:
        return None
    path = os.path.join(root, "engine", "setup", "np-ste-lint.py")
    return path if os.path.isfile(path) else None


def _lint_score(text, timeout_s):
    """Return (per100w, [(rule, count), ...]) or (None, []) when unavailable."""
    script = _lint_path()
    if not script or not text.strip():
        return (None, [])
    try:
        proc = subprocess.run(
            [sys.executable, script], input=text, capture_output=True,
            text=True, timeout=timeout_s, check=False)
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return (None, [])
    per100 = data.get("total_per100w")
    if per100 is None:
        rules = data.get("per100w_by_rule") or {}
        per100 = sum(rules.values()) if rules else None
    if per100 is None:
        return (None, [])
    violations = data.get("violations") or {}
    top = sorted(((k, v) for k, v in violations.items() if v),
                 key=lambda kv: -kv[1])[:3]
    return (float(per100), top)


def _check_diff(turn):
    md = [p for p in turn.edits
          if p.lower().endswith(".md") and not _SPEC_DOC.search(p)]
    if not md or any("np-md-diff" in d for d in turn.delivery):
        return ""
    names = ", ".join(sorted({os.path.basename(p) for p in md})[:5])
    return ("This turn changed %s without delivering a rendered diff. "
            "See np-flow-deliver-diff." % names)


def _check_form(turn, timeout_s):
    score, top = _lint_score(turn.final_text, timeout_s)
    if score is None:
        return ""
    try:
        threshold = float(np_toggle.param("turn_gate.form_threshold", "12") or 12)
    except (TypeError, ValueError):
        threshold = 12.0
    if score <= threshold:
        return ""
    detail = ", ".join("%s=%d" % (k, v) for k, v in top) or "see np-ste-lint.py"
    return ("Closing message scores %.1f violations per 100 words against a "
            "threshold of %.0f (%s). See np-flow-concise-output."
            % (score, threshold, detail))


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

    try:
        timeout_s = float(np_toggle.param("turn_gate.timeout_s", "5") or 5)
    except (TypeError, ValueError):
        timeout_s = 5.0

    warns = []
    if _mode("turn_gate.diff", "warn") != "off":
        warns.append(_check_diff(turn))
    if _mode("turn_gate.form", "warn") != "off":
        warns.append(_check_form(turn, timeout_s))
    warns = [w for w in warns if w]

    ui_files = [p for p in turn.edits if _is_ui(p)]
    ui_tripped = ui_mode != "off" and bool(ui_files) and not turn.delivery

    if ui_tripped:
        names = ", ".join(sorted({os.path.basename(p) for p in ui_files})[:5])
        message = ("This turn edited %s but never showed the result. %s"
                   % (names, _LADDER))
        # A block and a warn are different top-level contracts. Fold warns into
        # the reason so no finding is lost and no undefined shape is emitted.
        if warns:
            message += " Also: " + " ".join(warns)
        return _block(message) if ui_mode == "block" else _warn(message)

    return _warn(" ".join(warns)) if warns else ""
