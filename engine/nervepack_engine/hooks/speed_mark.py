"""UserPromptSubmit hook: mark a session as speed mode.

Writes the marker np_speed reads. Never prints, never blocks, fails open.
"""
import json

import np_speed
from nervepack_engine.hooks import spec_review


def run(payload_text, *_args):
    try:
        payload = json.loads(payload_text or "{}")
        if payload.get("hook_event_name") != "UserPromptSubmit":
            return ""
        # Cheap regex first: most prompts are not speed prompts, skip the file checks.
        if np_speed.names_speed_prompt(payload):
            if not np_speed.transcript_ok(payload):
                return ""
            sid = payload.get("session_id")
            if not np_speed.mark(sid):
                spec_review.log_verdict("MARKFAIL", sid, "speed-mode marker not written")
    except Exception:
        pass
    return ""
