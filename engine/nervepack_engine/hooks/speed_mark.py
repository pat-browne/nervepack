"""PreToolUse (Skill) and UserPromptSubmit hook: mark a session as speed mode.

Writes the marker np_speed reads. Never prints, never blocks, fails open.
"""
import json

import np_speed


def run(payload_text, *_args):
    try:
        payload = json.loads(payload_text or "{}")
        if np_speed.names_speed_skill(payload):
            np_speed.mark(payload.get("session_id"), payload.get("cwd") or "")
    except Exception:
        pass
    return ""
