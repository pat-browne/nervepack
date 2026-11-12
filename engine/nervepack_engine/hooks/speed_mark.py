"""UserPromptSubmit hook: mark a session as speed mode.

Writes the marker np_speed reads. Never prints, never blocks, fails open.
"""
import json

import np_speed


def run(payload_text, *_args):
    try:
        payload = json.loads(payload_text or "{}")
        if payload.get("hook_event_name") != "UserPromptSubmit":
            return ""
        tp = payload.get("transcript_path")
        if tp and np_speed.transcript_session(tp) != payload.get("session_id"):
            return ""
        if np_speed.names_speed_prompt(payload):
            np_speed.mark(payload.get("session_id"), payload.get("cwd") or "")
    except Exception:
        pass
    return ""
