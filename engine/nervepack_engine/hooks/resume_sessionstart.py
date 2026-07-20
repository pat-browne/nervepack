"""Bash-free port of np-resume-sessionstart.sh — SessionStart resume-pointer
writer: the reliable-trigger backstop for the resume-pointer feature. Since
np-resume-recall.py's live throttled writer can miss the final tick before a
session ends, this reconstructs the pointer for the most-recent COMPLETED
PRIOR session from disk on every new SessionStart. Skips the current (active)
session, agent-* subagent transcripts, and anything unsettled (mtime younger
than MIN_AGE_SEC). Newest-first scan -- the first survivor is the most-recent
completed prior session. No --throttle: SessionStart always forces a fresh
write. Fail-open: always returns "" (this hook has no stdout output, matching
the bash original).
"""
import json
import os
import re
import time

import np_toggle
from nervepack_engine.hooks import resume_write

_CWD_RE = re.compile(r'"cwd":"([^"]*)"')


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _min_age_sec():
    try:
        return int(os.environ.get("NP_RESUME_MIN_AGE_SEC", "120"))
    except ValueError:
        return 120


def _mtime(path):
    try:
        return int(os.stat(path).st_mtime)
    except OSError:
        return None


def _extract_cwd(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _CWD_RE.search(line)
                if m:
                    try:
                        return json.loads('"' + m.group(1) + '"')
                    except ValueError:
                        return m.group(1)
    except OSError:
        pass
    return None


def run(payload_text):
    if not np_toggle.enabled("resume"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        payload = {}
    cur_sid = payload.get("session_id") or ""
    cur_cwd = payload.get("cwd") or ""

    projects_dir = os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.join(_home(), ".claude", "projects")
    if not os.path.isdir(projects_dir):
        return ""

    min_age = _min_age_sec()
    now = int(time.time())

    candidates = []
    for root, _dirs, files in os.walk(projects_dir):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(root, name)
            mt = _mtime(path) or 0
            candidates.append((mt, path))
    candidates.sort(reverse=True)  # newest-first

    prior_sid = prior_tpath = None
    for _mt, tpath in candidates:
        sid = os.path.basename(tpath)[:-len(".jsonl")]
        if not sid or sid.startswith("agent-") or sid == cur_sid:
            continue
        mt = _mtime(tpath)
        mt = mt if mt is not None else now
        if now - mt < min_age:
            continue
        prior_sid, prior_tpath = sid, tpath
        break

    if not prior_sid:
        return ""

    prior_cwd = _extract_cwd(prior_tpath) or cur_cwd or _home()

    try:
        resume_write.write(session=prior_sid, transcript=prior_tpath, cwd=prior_cwd)
    except Exception:
        pass

    return ""
