"""Speed-mode marker: which sessions run np-flow-speed.

A human slash prompt writes one file per session id under the cache dir.

A Skill tool call never marks: the gated agent must not silence its own gate.

spec-review reads it and stays silent.

Subagent payloads carry the parent session_id, so the plain lookup covers them.

Fallback: transcript_path shaped like <parent-sid>/subagents/agent-*.jsonl.

Every error path answers "not speed mode", so a gate keeps its normal verdict.
"""
import hashlib
import json
import os
import re
import time

try:
    import pwd
except ImportError:  # no passwd database: the marker is never written
    pwd = None

import np_dirs
import np_host
import np_toggle

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
_PROMPT = re.compile(r"^\s*/(np-flow-speed|np-speed)\b")
# Claude Code names a subagent transcript <parent-sid>/subagents/agent-*.jsonl.
# A change to that layout stops the fallback matching, and the gate then asks.
_PARENT_FROM_TRANSCRIPT = re.compile(r"/([^/]+)/subagents/agent-[^/]+\.jsonl$")


def _dir():
    return os.environ.get("NP_SPEED_DIR") or np_dirs.cache_path("speed-mode")


def _path(sid):
    sid = str(sid)
    # Dots pass the character filter, so a leading dot must go: no id may
    # resolve to "." or "..".
    safe = (_UNSAFE.sub("_", sid).lstrip(".") or "unknown")[:128]
    if safe != sid:
        # The id was altered, so two ids could share a name. Tell them apart.
        safe += "-" + hashlib.sha1(sid.encode("utf-8", "replace")).hexdigest()[:12]
    return os.path.join(_dir(), safe)


def mark(sid):
    """Record sid as a speed-mode session. Returns True when written."""
    if not sid or sid == "unknown":
        return False
    try:
        os.makedirs(_dir(), exist_ok=True)
        with open(_path(sid), "w", encoding="utf-8") as fh:
            json.dump({"ts": time.time()}, fh)
        return True
    except OSError:
        return False


def names_speed_prompt(payload):
    """True when the human's prompt starts with /np-flow-speed or /np-speed."""
    if not isinstance(payload, dict) or payload.get("tool_name"):
        return False
    return bool(_PROMPT.match(str(payload.get("prompt") or "")))


def _ttl_s():
    try:
        h = float(np_toggle.param("gates.speed_silent_ttl_h", "12") or "12")
        if h > 0:
            return h * 3600
    except (TypeError, ValueError):
        pass
    return 12 * 3600


def _fresh(sid):
    """True when sid has a marker younger than the ttl."""
    try:
        with open(_path(sid), encoding="utf-8") as fh:
            ts = float(json.load(fh).get("ts", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    return time.time() - ts <= _ttl_s()


def transcript_session(path):
    """Session id named by a transcript path, or "" when it names none."""
    path = str(path or "")
    m = _PARENT_FROM_TRANSCRIPT.search(path)
    if m:
        return m.group(1)
    base = os.path.basename(path)
    return base[:-6] if base.endswith(".jsonl") else ""


def transcript_ok(payload):
    """True when the payload's transcript is a real file under the passwd home's
    .claude/projects and its resolved name matches session_id. Fails closed."""
    try:
        tp = payload.get("transcript_path")
        sid = payload.get("session_id")
        if not tp or not sid or pwd is None or not os.path.isfile(tp):
            return False
        home = pwd.getpwuid(os.getuid()).pw_dir
        root = os.path.realpath(np_host.default_under("transcripts", home))
        if not os.path.isdir(root):
            return False
        real = os.path.realpath(tp)
        if os.path.commonpath([root, real]) != root:
            return False
        return transcript_session(real) == sid
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return False


def is_speed(payload):
    """True when this hook payload belongs to a fresh speed-mode session."""
    try:
        if not isinstance(payload, dict):
            return False
        if not np_toggle.enabled("gates.speed_silent"):
            return False
        sid = payload.get("session_id")
        if sid and _fresh(sid):
            return True
        m = _PARENT_FROM_TRANSCRIPT.search(str(payload.get("transcript_path") or ""))
        return bool(m) and _fresh(m.group(1))
    except Exception:
        return False
