"""Bash-free port of np-backcapture-sweep.sh — the SessionStart back-capture
sweep. See the bash original's header comment for the full rationale (Claude
Code kills slow SessionEnd `claude -p` hooks before they finish, and `/exit`
doesn't fire SessionEnd at all, so this SessionStart sweep is the reliable
backstop: it scans completed prior-session transcripts and, for any with no
metrics record yet, runs capture + evaluate against the saved transcript).

Calls np_capture.capture() / np_evaluator.evaluate() IN-PROCESS rather than
shelling out to episodic-capture.sh / np-evaluator.sh — shelling to the .sh
originals would silently reintroduce the Git-bash dependency this migration
exists to remove. capture_fn/evaluate_fn are injectable for tests.

Two phases, exactly mirroring the bash original:
  Phase A (discovery): any *.jsonl under CLAUDE_PROJECTS_DIR modified within
    the `backcapture_days` window, not yet seen or queued, gets a queue file
    written (one-way ratchet — once queued it stays tracked regardless of the
    transcript's mtime aging past the window).
  Phase B (processing): drain the queue oldest-enqueued-first (by the mtime
    recorded AT ENQUEUE TIME, not re-derived), capped at `backcapture_max` per
    sweep. Claim atomically (os.O_EXCL) before capturing so a concurrent sweep
    can't double-process the same session.

Queue-file JSON shape ({"sid","mtime","transcript_path","cwd"}) and the
~/.cache/nervepack/backcapture-{seen,queue} directory layout are byte-
compatible with the bash version, so a live queue populated by the bash sweep
on a real machine keeps working after cutover. stdlib only.
"""
import json
import os
import re
import time

import np_capture
import np_content
import np_evaluator
import np_toggle

_CWD_RE = re.compile(r'"cwd":"([^"]*)"')


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _log_path():
    return os.environ.get("BACKCAPTURE_LOG") or os.path.join(
        _home(), ".cache", "nervepack", "backcapture.log")


def _log(msg):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fh.write("%s backcapture: %s\n" % (ts, msg))
    except OSError:
        pass


def _projects_dir():
    return os.environ.get("CLAUDE_PROJECTS_DIR") or os.path.join(_home(), ".claude", "projects")


def _seen_dir():
    return os.environ.get("BACKCAPTURE_SEEN_DIR") or os.path.join(
        _home(), ".cache", "nervepack", "backcapture-seen")


def _queue_dir():
    return os.environ.get("BACKCAPTURE_QUEUE_DIR") or os.path.join(
        _home(), ".cache", "nervepack", "backcapture-queue")


def _metrics_path():
    override = os.environ.get("BACKCAPTURE_METRICS")
    if override:
        return override
    return os.path.join(np_content.content_dir(), "dashboard", "data", "metrics.jsonl")


def _min_age_sec():
    try:
        return int(os.environ.get("BACKCAPTURE_MIN_AGE_SEC", "120"))
    except ValueError:
        return 120


def _param_int(key, default):
    try:
        return int(np_toggle.param(key, str(default)))
    except (ValueError, TypeError):
        return default


def _already_in_metrics(sid, metrics_path):
    if not os.path.isfile(metrics_path):
        return False
    try:
        with open(metrics_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if sid in line:
                    return True
    except OSError:
        pass
    return False


def _extract_cwd(tpath):
    try:
        with open(tpath, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _CWD_RE.search(line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def _touch(path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass
    except OSError:
        pass


def _claim(seen_dir, sid):
    """Atomic claim, mirroring bash's `( set -C; : > "$SEEN_DIR/$sid" )`."""
    path = os.path.join(seen_dir, sid)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except (FileExistsError, OSError):
        return False


def _write_queue_file(path, sid, mt, tpath, cwd):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"sid": sid, "mtime": mt, "transcript_path": tpath, "cwd": cwd}, fh,
                      separators=(",", ":"))
    except OSError:
        pass


def _discover(projects_dir, days, min_age_sec, cur_sid, seen_dir, queue_dir, metrics_path, now):
    cutoff = now - days * 86400
    for root, _dirs, files in os.walk(projects_dir):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            tpath = os.path.join(root, name)
            sid = name[:-len(".jsonl")]
            if not sid or sid.startswith("agent-") or sid == cur_sid:
                continue
            try:
                mt = int(os.stat(tpath).st_mtime)
            except OSError:
                mt = now
            if mt < cutoff:
                continue                                   # outside discovery window on first sighting
            if now - mt < min_age_sec:
                continue                                   # unsettled / active
            seen_marker = os.path.join(seen_dir, sid)
            if os.path.exists(seen_marker):
                continue
            queue_file = os.path.join(queue_dir, sid)
            if os.path.exists(queue_file):
                continue
            if _already_in_metrics(sid, metrics_path):
                _touch(seen_marker)
                continue
            cwd = _extract_cwd(tpath) or _home()
            _write_queue_file(queue_file, sid, mt, tpath, cwd)


def _process(queue_dir, seen_dir, metrics_path, max_per_sweep, capture_fn, evaluate_fn):
    pending = []
    try:
        names = os.listdir(queue_dir)
    except OSError:
        names = []
    for sid in names:
        qpath = os.path.join(queue_dir, sid)
        if not os.path.isfile(qpath):
            continue
        if os.path.exists(os.path.join(seen_dir, sid)):
            continue
        try:
            with open(qpath, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        mt = rec.get("mtime")
        if mt is None:
            continue
        pending.append((mt, sid, rec))
    pending.sort(key=lambda t: t[0])

    processed = 0
    for _mt, sid, rec in pending:
        if processed >= max_per_sweep:
            break
        seen_marker = os.path.join(seen_dir, sid)
        if os.path.exists(seen_marker):
            continue
        tpath = rec.get("transcript_path") or ""
        cwd = rec.get("cwd") or _home()
        if not tpath or not os.path.isfile(tpath):
            _touch(seen_marker)
            _log("dropped %s (transcript missing or queue entry unreadable)" % sid)
            continue
        if _already_in_metrics(sid, metrics_path):
            _touch(seen_marker)
            continue
        if not _claim(seen_dir, sid):
            continue
        payload = {"session_id": sid, "transcript_path": tpath, "cwd": cwd}
        try:
            capture_fn(payload, "session-end")
        except Exception:
            pass
        try:
            evaluate_fn(payload)
        except Exception:
            pass
        processed += 1
        _log("back-captured %s (project %s)" % (sid, os.path.basename(cwd)))
    return processed


def run(payload_text, capture_fn=None, evaluate_fn=None):
    """Entry point called by cli.py. `capture_fn`/`evaluate_fn` default to the
    real np_capture.capture / np_evaluator.evaluate; tests inject stubs."""
    if os.environ.get("NERVEPACK_AGENT"):        # re-entry guard — invariant 2
        return
    if not np_toggle.enabled("memory.backcapture"):
        return

    projects_dir = _projects_dir()
    if not os.path.isdir(projects_dir):
        return

    seen_dir = _seen_dir()
    queue_dir = _queue_dir()
    try:
        os.makedirs(seen_dir, exist_ok=True)
        os.makedirs(queue_dir, exist_ok=True)
    except OSError:
        return

    metrics_path = _metrics_path()
    days = _param_int("memory.backcapture_days", 7)
    max_per_sweep = _param_int("memory.backcapture_max", 5)
    min_age_sec = _min_age_sec()

    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        payload = {}
    cur_sid = payload.get("session_id") or ""

    now = int(time.time())
    _discover(projects_dir, days, min_age_sec, cur_sid, seen_dir, queue_dir, metrics_path, now)
    processed = _process(queue_dir, seen_dir, metrics_path, max_per_sweep,
                          capture_fn or np_capture.capture, evaluate_fn or np_evaluator.evaluate)

    if processed > 0:
        pending = 0
        for name in os.listdir(queue_dir):
            if os.path.isfile(os.path.join(queue_dir, name)) and not os.path.exists(
                    os.path.join(seen_dir, name)):
                pending += 1
        _log("sweep done: %d session(s) captured, %d still queued" % (processed, pending))
