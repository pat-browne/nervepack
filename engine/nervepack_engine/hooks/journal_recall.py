"""Session-journal read-back hook, dispatched as `cli.py hook journal-recall`.

Registered on SessionStart and UserPromptSubmit. SessionStart injects the journal
when source is compact or resume. UserPromptSubmit injects only as a fallback for
an interrupted SessionStart. Fail-open.
"""
import json

import np_journal


def run(payload_text):
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        payload = {}
    event = payload.get("hook_event_name") or "SessionStart"
    try:
        if event == "UserPromptSubmit":
            text = np_journal.recall_fallback(payload)
        else:
            text = np_journal.recall_sessionstart(payload)
    except Exception:
        text = ""
    if not text:
        return ""
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
        separators=(",", ":"))
