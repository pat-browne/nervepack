"""UserPromptSubmit hook: inject a once-per-session reminder to invoke the
security-review skill when the prompt contains security- or vulnerability-
related keywords. Fail-open: returns "" on any early-exit path.
"""
import json
import os
import re

import np_toggle

_PATTERN = re.compile(r"security|vulnerabilit|exploit|injection|xss|csrf|cve")
_MSG = ("Security-review trigger (Nervepack): this prompt mentions security or "
        "vulnerability keywords. Before proceeding, invoke the security-review skill "
        "to apply a structured security checklist. If your host has a dedicated "
        "skill (e.g. security-review), invoke it first.")


def _state_dir():
    return os.environ.get("NP_SECURITY_RECALL_STATE") or "/tmp/nervepack-security-recall"


def run(payload_text):
    if not np_toggle.enabled("skills.security_recall"):
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
    np_toggle.signal(sid, "security-recall")

    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": _MSG}},
        separators=(",", ":"))
