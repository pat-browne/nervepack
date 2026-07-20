"""Bash-free port of skill-trigger-recall.sh — UserPromptSubmit hook: inject a
once-per-session reminder to follow a disciplined skill-authoring process when
the prompt matches a skill-writing pattern. Host-neutral (names a skill-
authoring skill only as an optional example). Fail-open: returns "" on any
early-exit path, matching the bash original's silent `exit 0`.
"""
import json
import os
import re

import np_toggle

_PATTERN = re.compile(r"skill.*refactor|refactor.*skill|skill\.md")
_MSG = ("Skill-writing trigger (Nervepack): this prompt matches a skill-writing pattern. "
        "Before proceeding, follow a disciplined skill-authoring process (spec the skill, "
        "write it, then verify with a subagent application test). If your host has a "
        "dedicated skill-authoring skill (e.g. superpowers:writing-skills), invoke it first.")


def _state_dir():
    return os.environ.get("NP_SKILL_TRIGGER_STATE") or "/tmp/nervepack-skill-trigger"


def run(payload_text):
    if not np_toggle.enabled("skills.trigger_recall"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    sid = payload.get("session_id") or "unknown"
    if not sid or sid == "unknown":
        return ""
    prompt = (payload.get("prompt") or "").lower()
    if not prompt:
        return ""

    state_dir = _state_dir()
    try:
        os.makedirs(state_dir, exist_ok=True)
    except OSError:
        return ""
    fired = os.path.join(state_dir, "fired_" + sid.replace("/", "_"))
    if os.path.exists(fired):
        return ""

    if not _PATTERN.search(prompt):
        return ""

    try:
        with open(fired, "a", encoding="utf-8"):
            pass
    except OSError:
        pass
    np_toggle.signal(sid, "skill-trigger-recall")

    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": _MSG}},
        separators=(",", ":"))
