"""UserPromptSubmit hook: inject a once-per-session reminder to invoke the
security-review skill when the prompt contains security- or vulnerability-
related keywords. Fail-open: returns "" on any early-exit path.
"""
import json
import os
import re

import np_toggle
import np_dirs

# Fire on review INTENT, not on any mention of the word. A bare "security"
# match fired on prompts about security groups or about this hook, and the
# evaluator then logged a false "skill not invoked" miss for each one.
_REVIEW = r"(?:review|audit|check|scan|assess|harden|pentest|threat[- ]?model)\w*"
_SUBJECT = r"(?:security|secure|vulnerab\w*)"
_PATTERN = re.compile(
    r"\b" + _REVIEW + r"\b[^.?!\n]{0,40}?\b" + _SUBJECT
    + r"|\b" + _SUBJECT + r"\s+" + _REVIEW
    + r"|vulnerab|exploit|\bxss\b|\bcsrf\b|\bssrf\b|\bcve-?\d"
    + r"|\b(?:sql|command|shell|code|ldap|xpath|prompt)\s+injection|injection\s+attack")
_MSG = ("Security-review trigger (Nervepack): this prompt asks for a security or "
        "vulnerability review. Before proceeding, invoke the security-review skill "
        "to apply a structured security checklist. If your host has a dedicated "
        "skill (e.g. security-review), invoke it first.")


def _state_dir():
    return os.environ.get("NP_SECURITY_RECALL_STATE") or np_dirs.cache_path("security-recall-state")


def run(payload_text):
    # param, not a bare sub-toggle -- see skill_trigger_recall.run().
    if not np_toggle.enabled("skills") or np_toggle.param("skills.security_recall", "on") != "on":
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
