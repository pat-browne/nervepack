"""Stop hook: catch a usage-limit violation the moment it happens.

Reads the transcript this turn wrote and hands it to the shared detector.
Always returns "" -- never blocks, only schedules a background nudge.

The `quota-watch` cron re-scans every 30 minutes as a backstop, for a
limit hit mid-tool-call where no Stop event fires at all.
"""
import json

import np_quota_watch


def run(payload_text, *_args):
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""

    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path:
        return ""

    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""

    try:
        np_quota_watch.detect_and_schedule(text, "stop-hook")
    except Exception:
        pass
    return ""
