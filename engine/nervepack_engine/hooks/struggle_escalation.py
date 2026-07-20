"""Bash-free port of struggle-escalation.sh — UserPromptSubmit hook: after
MIN_PROMPTS have passed, if lesson-guard fired >= MIN_STRUGGLES times this
session (per the session's signal log), inject a one-time reminder to check
skill-applicability or np-core-suggestions-review. Fires at most once per
session. Fail-open: returns "" on any early-exit path.

The prompt-count check uses the PRE-increment count (mirroring bash: it reads
pcount, THEN writes pcount+1 to the counter file, THEN checks the OLD pcount
against MIN_PROMPTS) — a subtle off-by-one to preserve exactly.
"""
import json
import os

import np_toggle


def _min_struggles():
    try:
        return int(os.environ.get("NP_ESCALATION_MIN_STRUGGLES", "2"))
    except ValueError:
        return 2


def _min_prompts():
    try:
        return int(os.environ.get("NP_ESCALATION_MIN_PROMPTS", "3"))
    except ValueError:
        return 3


def _state_dir():
    return os.environ.get("NP_ESCALATION_STATE") or "/tmp/nervepack-escalation"


def _signal_log_path(sid):
    base = os.environ.get("NP_SIGNAL_DIR") or os.path.join(
        os.environ.get("HOME") or os.path.expanduser("~"), ".cache", "nervepack", "session-signals")
    return os.path.join(base, sid.replace("/", "_") + ".log")


def run(payload_text):
    if not np_toggle.enabled("evaluator.escalation"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    sid = payload.get("session_id") or "unknown"
    if not sid or sid == "unknown":
        return ""

    state_dir = _state_dir()
    try:
        os.makedirs(state_dir, exist_ok=True)
    except OSError:
        return ""

    fired = os.path.join(state_dir, "fired_" + sid.replace("/", "_"))
    if os.path.exists(fired):
        return ""

    pcnt_file = os.path.join(state_dir, "cnt_" + sid.replace("/", "_"))
    try:
        with open(pcnt_file, encoding="utf-8") as fh:
            pcount = int(fh.read().strip() or "0")
    except (OSError, ValueError):
        pcount = 0
    try:
        with open(pcnt_file, "w", encoding="utf-8") as fh:
            fh.write(str(pcount + 1))
    except OSError:
        pass
    if pcount < _min_prompts():                # pre-increment value, matches bash
        return ""

    log_path = _signal_log_path(sid)
    pg_count = 0
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("lesson-guard"):
                    pg_count += 1
    except OSError:
        pg_count = 0
    if pg_count < _min_struggles():
        return ""

    try:
        with open(fired, "a", encoding="utf-8"):
            pass
    except OSError:
        pass
    np_toggle.signal(sid, "struggle-escalation")

    msg = ("Mid-session escalation (Nervepack): %d repeated pattern-trigger events detected "
           "in this session. Consider invoking np-core-suggestions-review to act on past "
           "evaluator suggestions, or check whether a skill applies before continuing." % pg_count)
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}},
        separators=(",", ":"))
