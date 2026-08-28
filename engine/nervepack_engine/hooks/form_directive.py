"""UserPromptSubmit hook: inject the output contract before the draft exists.

This is the PREVENTIVE half of the form pair. `turn_gate` is corrective, and a
corrective gate on a Stop event is always too late: the closing message reached
the reader before the hook ran, so the best a block can do is append a
correction under text the reader already saw. The only way to avoid that is for
the FIRST draft to be clean, which means the contract has to be in front of the
model while it writes rather than after.

Cheap on purpose. One short block of text, no file scanning, no model call. It
fails open like every other nervepack hook: any error returns "" and the turn
proceeds with no injection.

The text is overridable. The engine ships a default so a fresh forker gets
something sane, and `<content_dir>/config/form-directive.txt` replaces it
wholesale for anyone whose contract differs. Nothing about one person's house
style belongs in a repo other people fork.

See change-specs/feat-form-gate-enforcement.md.
"""
import json
import os

import np_content
import np_dirs
import np_toggle

# Obeys its own rules, deliberately. A directive that breaks the contract it
# states is the failure np-flow-concise-output calls self-application.
_DEFAULT = """Output contract (np-flow-concise-output). Applies to this reply and to every
file, commit message, description, and comment written this turn.

- Lead with the answer, the fact, or the deliverable. No preamble, no restated
  question, no narration of what you are about to do.
- Cut pleasantries, hedges, and self-grading. Compress rather than omit: never
  drop a fact that changes the reader's next decision.
- Active voice. The short common word: use not utilize, start not initiate,
  make sure not ensure, show not demonstrate, about not regarding.
- Zero tolerance, not rate-based: no em dash, no semicolon, no contraction, no
  marketing adjective (seamless, robust, powerful, effortless, comprehensive).
- One instruction per sentence, 20 words or fewer. Six sentences per paragraph.

A status question ("where are we", "what is left", "are we done") gets four
parts in order: Done, Left, Links to every artifact, and open questions
restated in full."""


def _text():
    """The contract to inject. Overlay file if present, else the default."""
    try:
        root = np_content.content_dir()
    except Exception:
        root = ""
    if root:
        path = os.path.join(root, "config", "form-directive.txt")
        try:
            with open(path, encoding="utf-8") as fh:
                custom = fh.read().strip()
            if custom:
                return custom
        except OSError:
            pass
    return _DEFAULT


def _state_dir():
    return os.environ.get("NP_FORM_DIRECTIVE_DIR") or np_dirs.cache_path("form-directive")


def _already_sent(sid):
    """True when session cadence is in force and this session was served.

    Only consulted for cadence=session. Any filesystem error answers False,
    which injects again -- a duplicated directive is harmless, a missing one is
    the failure this hook exists to prevent.
    """
    marker = os.path.join(_state_dir(), sid.replace("/", "_"))
    if os.path.exists(marker):
        return True
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        with open(marker, "a", encoding="utf-8"):
            pass
    except OSError:
        pass
    return False


def run(payload_text, *_args):
    if not np_toggle.enabled("form_directive"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""

    cadence = (np_toggle.param("form_directive.cadence", "turn")
               or "turn").strip().lower()
    sid = payload.get("session_id") or "unknown"
    if cadence == "session" and _already_sent(sid):
        return ""

    try:
        body = _text()
    except Exception:
        return ""
    if not body.strip():
        return ""

    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                "additionalContext": body}},
        separators=(",", ":"))
