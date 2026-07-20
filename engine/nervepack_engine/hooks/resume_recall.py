"""Bash-free port of np-resume-recall.sh — UserPromptSubmit hook: resume-
pointer surfacer + live throttled writer (no LLM calls).

ORDER MATTERS: surface first (read the pointer left by a PRIOR session), THEN
write the CURRENT session's own pointer via resume_write.write(...,
throttle=True) in-process. Because the write sets session_id==current,
subsequent prompts in this session correctly see a same-session pointer and
stay silent -- surfacing must happen before the write, else it would always
compare against itself. Fail-open: returns "" on any early-exit path.
"""
import json
import os
import time

import np_toggle
from nervepack_engine.hooks import resume_write


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _pointer_path():
    return os.environ.get("NP_RESUME_POINTER") or os.path.join(_home(), ".cache", "nervepack", "resume-pointer.json")


def _state_dir():
    return os.environ.get("NP_RESUME_STATE_DIR") or os.path.join(_home(), ".cache", "nervepack", "resume-recall-state")


def _is_fresh(age, max_age):
    """Factored out so tests can mock it for a non-vacuity check, mirroring
    the bash test's own broken-copy technique."""
    return 0 <= age < max_age


def _format_ago(age):
    if age < 3600:
        n = max(1, age // 60)
        return "~%dm ago" % n
    return "~%dh ago" % (age // 3600)


def run(payload_text):
    if not np_toggle.enabled("resume"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    sid = payload.get("session_id") or ""
    cwd = payload.get("cwd") or ""
    transcript_path = payload.get("transcript_path") or ""
    if not sid:
        return ""

    ctx = ""
    state_dir = _state_dir()
    marker = os.path.join(state_dir, "surfaced_" + sid.replace("/", "_"))
    if not os.path.isfile(marker):
        pointer_path = _pointer_path()
        if os.path.isfile(pointer_path):
            try:
                with open(pointer_path, encoding="utf-8") as fh:
                    ptr = json.load(fh)
            except (OSError, ValueError):
                ptr = None
            if ptr:
                p_sid = ptr.get("session_id") or ""
                p_ts = ptr.get("ts")
                if p_sid and p_sid != sid and isinstance(p_ts, int):
                    now = int(time.time())
                    try:
                        max_age = int(np_toggle.param("resume.max_age", "86400"))
                    except (ValueError, TypeError):
                        max_age = 86400
                    age = now - p_ts
                    if _is_fresh(age, max_age):
                        p_branch = ptr.get("git_branch") or ""
                        p_head = ptr.get("git_head") or ""
                        p_dirty = ptr.get("git_dirty") or False
                        p_ledger = ptr.get("sdd_ledger") or ""
                        p_plan = ptr.get("sdd_plan") or ""
                        p_last = ptr.get("last_user_instruction") or ""

                        ago = _format_ago(age)
                        dirty_note = " (dirty)" if p_dirty else ""
                        where = "%s@%s%s" % (p_branch or "unknown branch", p_head or "unknown", dirty_note)

                        msg = "A prior nervepack session (%s) was working in %s" % (ago, where)
                        if p_last:
                            msg += " — %s" % p_last
                        msg += ". Resume from"
                        parts = []
                        if p_ledger:
                            parts.append("the SDD ledger (%s)" % p_ledger)
                        if p_plan:
                            parts.append("plan %s" % p_plan)
                        parts.append("the branch")
                        msg += " " + " / ".join(parts) + ", or start fresh."

                        ctx = json.dumps(
                            {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                     "additionalContext": msg}},
                            separators=(",", ":"))
                        try:
                            os.makedirs(state_dir, exist_ok=True)
                            with open(marker, "a", encoding="utf-8"):
                                pass
                        except OSError:
                            pass

    if transcript_path and cwd:
        try:
            resume_write.write(session=sid, transcript=transcript_path, cwd=cwd, throttle=True)
        except Exception:
            pass

    return ctx
