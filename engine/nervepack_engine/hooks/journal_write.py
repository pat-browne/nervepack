"""Session-journal writer hook. Dispatched as `cli.py hook journal-write <mode>`.

mode `seed` runs on SessionStart, `checkpoint` runs on PreCompact. Side-effect
only, always returns "". Fail-open.
"""
import json

import np_journal


def run(payload_text, mode="seed"):
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        payload = {}
    try:
        if mode == "checkpoint":
            np_journal.checkpoint(payload)
        else:
            np_journal.seed(payload)
    except Exception:
        pass
    return ""
