"""UserPromptSubmit and SessionEnd hook for session claims. Fail-open."""
import hashlib
import json
import os
import time

import np_claims
import np_dirs
import np_toggle


def _bail(msg):
    try:
        path = np_dirs.cache_path("claims.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s claim-hook: %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg))
    except OSError:
        pass


def _prune_markers(state_dir):
    try:
        days = int(np_toggle.param("claims.stale_days", "7"))
    except (ValueError, TypeError):
        days = 7
    cutoff = time.time() - days * 86400
    for name in os.listdir(state_dir):
        path = os.path.join(state_dir, name)
        try:
            if name.startswith("surfaced_") and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            continue


def run(payload_text, mode="prompt"):
    try:
        if os.environ.get("NERVEPACK_AGENT"):
            return ""
        payload = json.loads(payload_text or "{}")
        sid = payload.get("session_id") or ""
        cwd = payload.get("cwd") or ""
        if not sid or not cwd or not np_claims.enabled():
            return ""
        if mode == "end":
            np_claims.release(sid, cwd)
            return ""
        np_claims.write(sid, cwd)
        pos = np_claims.position(sid, cwd)
        text = np_claims.render(pos)
        if not text:
            return ""
        ids = sorted(o.get("session_id", "") for o in pos.get("others") or [])
        key = hashlib.sha1(",".join(ids).encode("utf-8")).hexdigest()[:8]
        marker = np_dirs.cache_path("claims-state", "surfaced_%s_%s" % (sid.replace("/", "_"), key))
        if os.path.exists(marker):
            return ""
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        _prune_markers(os.path.dirname(marker))
        with open(marker, "a", encoding="utf-8"):
            pass
        return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                   "additionalContext": text}},
                          separators=(",", ":"))
    except Exception as exc:  # noqa: BLE001
        _bail("run: %r" % exc)
        return ""
