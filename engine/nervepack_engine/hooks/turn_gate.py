"""Stop and SubagentStop hook: the turn-completion gate.

Blocks a turn ONCE when it edited UI files and never showed the result, or
(when `turn_gate.form` is `block`) when the closing message fails the form
contract. This is the single hook in nervepack permitted to block, per the
amended ARCHITECTURE invariant 1. Every one of its own error paths still
returns "" and allows.

Order matters: stop_hook_active is checked before any parsing, toggle read, or
file access. The harness caps consecutive blocks at 8, but this gate must never
depend on that backstop.

**What blocking here can and cannot do.** A Stop hook fires after the closing
message already streamed to the reader. Blocking cannot un-send it; it can only
force a correction into the same turn. So every finding rides on ONE decision
and the reason forbids restating, which makes the continuation a replacement
rather than a second full answer. Keeping the FIRST draft clean is the job of
the `form_directive` UserPromptSubmit hook. This gate is the backstop for the
drafts prevention misses. See change-specs/feat-form-gate-enforcement.md.
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

# Sent with every block. Without it the model answers again in full and the
# reader sees the same content twice, which is the failure mode that kept this
# check pinned to warn.
_NO_RESTATE = ("Do not restate, re-explain, or summarize the message you just "
               "sent. The reader already has it. Send only the rewritten "
               "closing message, with nothing before or after it.")

_LADDER = ("Serve it and open it in the browser, or take a screenshot and show it. "
           "If the change has no visual surface (a refactor, a comment, a build "
           "tweak), say so plainly and finish -- that is a valid resolution and "
           "this gate will not ask twice.")


def _is_ui(path):
    return path.lower().endswith(_UI_EXT) and not _EXEMPT.search(path)


def _mode(param, default):
    value = (np_toggle.param(param, default) or default).strip().lower()
    return value if value in ("block", "warn", "off") else default


def _on(param, default):
    """A plain on/off toggle. `_mode` reads the block/warn/off ladder, which is
    a different vocabulary; sharing one reader would silently accept 'block' as
    an answer to 'should this lane run at all'."""
    return (np_toggle.param(param, default) or default).strip().lower() != "off"


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
    if not md:
        return ""
    if any("np-md-diff" in d for d in turn.delivery):
        return ""
    # A hand-typed diff pasted straight into the response is a valid delivery
    # too -- np-md-diff.py is one way to produce a diff, not the only one.
    if np_turn_parse.has_diff_shape(turn.final_text):
        return ""
    # SendUserFile fully delivers a file this turn CREATED (no base version
    # exists, so the skill prescribes sending the whole file, not a diff). An
    # EDITED file still needs a diff -- whole-filing it without one is exactly
    # the workaround the skill rules out, so this only clears when every
    # undelivered .md path was created, not merely edited, this turn.
    sent_file = any("sent a file to the user" in d for d in turn.delivery)
    if sent_file and all(p in turn.created for p in md):
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
            "threshold of %.1f (%s). See np-flow-concise-output."
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

    # A subagent hands text back to its caller and shows nothing to a human, so
    # the delivery checks (did you show the UI, did you render the diff) have no
    # subject there. Its prose still reaches a reader through the caller, so the
    # form check does apply.
    subagent = payload.get("hook_event_name") == "SubagentStop"
    if subagent and not _on("turn_gate.subagent", "on"):
        return ""

    try:
        timeout_s = float(np_toggle.param("turn_gate.timeout_s", "5") or 5)
    except (TypeError, ValueError):
        timeout_s = 5.0

    # Each finding is filed under the severity its own toggle names. Everything
    # blocking then leaves on a SINGLE decision -- blocking twice for one turn
    # would produce exactly the duplicate output this mode exists to avoid.
    blocking, advisory = [], []

    def _file(mode, message):
        if message:
            (blocking if mode == "block" else advisory).append(message)

    form_mode = _mode("turn_gate.form", "warn")
    if form_mode != "off":
        _file(form_mode, _check_form(turn, timeout_s))

    if not subagent:
        diff_mode = _mode("turn_gate.diff", "warn")
        if diff_mode != "off":
            _file(diff_mode, _check_diff(turn))

        ui_mode = _mode("turn_gate.ui", "block")
        ui_files = [p for p in turn.edits if _is_ui(p)]
        if ui_mode != "off" and ui_files and not turn.delivery:
            names = ", ".join(sorted({os.path.basename(p) for p in ui_files})[:5])
            _file(ui_mode, "This turn edited %s but never showed the result. %s"
                  % (names, _LADDER))

    if blocking:
        return _block(" ".join(blocking + advisory) + " " + _NO_RESTATE)
    return _warn(" ".join(advisory)) if advisory else ""
