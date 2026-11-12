"""Speed-mode marker: which sessions run np-flow-speed.

The skill call writes one file per session id under the cache dir.

spec-review and drift-guard read it and stay silent.

Subagent payloads carry the parent session_id, so the plain lookup covers them.

Fallback one: transcript_path shaped like <parent-sid>/subagents/agent-*.jsonl.

Fallback two: cwd under <root>/.claude/worktrees/agent-*, matched to a fresh
marker that recorded the same <root>.

Every error path answers "not speed mode", so a gate keeps its normal verdict.
"""
import json
import os
import re
import time

import np_dirs
import np_toggle

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_SKILL = re.compile(r"(^|[:/])np-(flow-)?speed$")
_PROMPT = re.compile(r"^\s*/(np-flow-speed|np-speed)\b")
_WORKTREE = re.compile(r"^(.*?)/\.claude/worktrees/agent-[^/]+")
_PARENT_FROM_TRANSCRIPT = re.compile(r"/([^/]+)/subagents/agent-[^/]+\.jsonl$")
_FRESH_S = 24 * 3600


def _dir():
    return os.environ.get("NP_SPEED_DIR") or np_dirs.cache_path("speed-mode")


def _path(sid):
    safe = (_UNSAFE.sub("_", str(sid)).lstrip(".") or "unknown")[:128]
    return os.path.join(_dir(), safe)


def mark(sid, cwd=""):
    """Record sid as a speed-mode session. Returns True when written."""
    if not sid or sid == "unknown":
        return False
    try:
        os.makedirs(_dir(), exist_ok=True)
        with open(_path(sid), "w", encoding="utf-8") as fh:
            json.dump({"ts": time.time(), "cwd": cwd or ""}, fh)
        return True
    except OSError:
        return False


def names_speed_skill(payload):
    """True when a Skill tool call or a prompt names np-flow-speed."""
    if not isinstance(payload, dict):
        return False
    ti = payload.get("tool_input")
    if payload.get("tool_name") == "Skill" and isinstance(ti, dict):
        return bool(_SKILL.search(str(ti.get("skill") or ti.get("name") or "").strip()))
    return bool(_PROMPT.search(str(payload.get("prompt") or "")))


def _marked_by_root(root):
    try:
        names = os.listdir(_dir())
    except OSError:
        return False
    now = time.time()
    for name in names:
        try:
            with open(os.path.join(_dir(), name), encoding="utf-8") as fh:
                data = json.load(fh)
            if now - float(data.get("ts", 0)) <= _FRESH_S and data.get("cwd") == root:
                return True
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return False


def is_speed(payload):
    """True when this hook payload belongs to a speed-mode session."""
    try:
        if not isinstance(payload, dict):
            return False
        if not np_toggle.enabled("gates.speed_silent"):
            return False
        sid = payload.get("session_id")
        if sid and os.path.isfile(_path(sid)):
            return True
        m = _PARENT_FROM_TRANSCRIPT.search(str(payload.get("transcript_path") or ""))
        if m and os.path.isfile(_path(m.group(1))):
            return True
        w = _WORKTREE.match(str(payload.get("cwd") or ""))
        return bool(w) and _marked_by_root(w.group(1))
    except Exception:
        return False
