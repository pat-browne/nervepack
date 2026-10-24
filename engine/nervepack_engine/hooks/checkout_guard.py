"""SessionStart hook (`cli.py hook checkout-guard`): warn when the engine or a
content overlay checkout is off main or behind origin/main. Silent when clean,
so the clean-case context stays empty. Uses the last-fetched ref only (no
network). Fail-open."""
import json
import sys

import np_checkout_guard
import np_toggle


def run(payload_text):
    if not np_toggle.enabled("checkout"):
        return ""
    try:
        text = np_checkout_guard.warning(*np_checkout_guard.scan())
    except Exception as exc:  # fail-open, but leave a trace on stderr
        sys.stderr.write("checkout-guard: skipped (%s)\n" % type(exc).__name__)
        text = ""
    if not text:
        return ""
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
        separators=(",", ":"))
