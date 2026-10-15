"""PostToolUse hook (matcher: Bash): after a successful PR merge or deploy,
tell the session to run np-core-capture-learning before ending the turn.
Detection is a regex list over the Bash command (SHIP_PATTERNS). A failed
command is skipped. Fail-open: returns "" on every early-exit path.
"""
import json
import re

import np_toggle

# (label, regex) pairs matched against the Bash command. Edit this list to
# widen or narrow detection.
SHIP_PATTERNS = [
    ("gh pr merge", r"\bgh\s+pr\s+merge\b"),
    ("az repos pr complete", r"\baz\s+repos\s+pr\s+update\b.*--status\s+completed\b"),
    ("git push to main", r"\bgit\b.*\bpush\b.*(?:\s|:|refs/heads/)(?:main|master)\b"),
    ("databricks bundle deploy", r"\bdatabricks\s+bundle\s+deploy\b"),
    ("terragrunt apply", r"\bterragrunt\b.*\b(?:run-all\s+)?apply\b"),
    ("terraform apply", r"\bterraform\b.*\bapply\b"),
    ("az deployment", r"\baz\s+deployment\b.*\bcreate\b"),
    ("npm run deploy", r"\bnpm\s+run\s+deploy\b"),
]
_COMPILED = [(label, re.compile(rx)) for label, rx in SHIP_PATTERNS]
_SKIP_RE = re.compile(r"--dry-run\b")
# A branch delete is not a ship: `git push --delete`, `-d`, or `:main`.
_PUSH_DELETE_RE = re.compile(r"\s(?:--delete|-d)(?:\s|$)|\s:(?:main|master)\b")
_FAIL_RE = re.compile(r"^\s*(?:error|fatal|Error|ERROR)\b[:!\s]", re.MULTILINE)

_MSG = ("Post-ship capture (Nervepack): this command shipped work ({label}). "
        "Before ending this turn, invoke the np-core-capture-learning skill to "
        "capture what this change taught: gotchas hit, fixes, decisions. "
        "Skip it only if nothing new was learned, and say so in one line.")


def detect(command):
    """Return the matched ship label for a command, or None."""
    if not command or _SKIP_RE.search(command):
        return None
    for label, rx in _COMPILED:
        if rx.search(command):
            if label == "git push to main" and _PUSH_DELETE_RE.search(command):
                return None
            return label
    return None


def failed(response):
    """True when the tool result shows a non-zero exit or an error."""
    if isinstance(response, str):
        return bool(_FAIL_RE.search(response))
    if not isinstance(response, dict):
        return False
    if response.get("is_error") or response.get("isError") or response.get("interrupted"):
        return True
    for key in ("exit_code", "exitCode", "returncode", "return_code"):
        code = response.get(key)
        if isinstance(code, int) and code != 0:
            return True
    text = "\n".join(str(response.get(k) or "") for k in ("stdout", "stderr", "error"))
    return bool(_FAIL_RE.search(text))


def run(payload_text):
    if not np_toggle.enabled("post_ship"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    if payload.get("tool_name") != "Bash":
        return ""
    command = (payload.get("tool_input") or {}).get("command") or ""
    label = detect(command)
    if not label or failed(payload.get("tool_response")):
        return ""
    sid = payload.get("session_id") or ""
    if sid:
        np_toggle.signal(sid, "post-ship-capture")
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                "additionalContext": _MSG.format(label=label)}},
        separators=(",", ":"))
