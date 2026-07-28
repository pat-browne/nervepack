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

Whole-sweep lock: the per-session claim above only stops two sweeps
double-processing the SAME session -- it does nothing to stop many sweeps
running at once against DIFFERENT sessions. SessionStart fires once per
Claude Code session, so a large fleet of parallel sessions each starting
around the same time previously fanned out one `claude -p` capture+evaluate
loop per sweep, all concurrently (observed: dozens of live `claude` child
processes driving sustained CPU load / thermal throttling). `_acquire_lock`
serializes sweeps to one at a time system-wide (PID-stamped, same
os.O_EXCL idiom as `_claim`, stale-PID reclaim so a crashed holder can't
wedge future sweeps); a sweep that loses the race just exits (fail open,
invariant 1) -- the persistent queue means the next sweep to win picks up
the backlog, nothing is lost.

Queue-file JSON shape ({"sid","mtime","transcript_path","cwd"}) and the
~/.cache/nervepack/backcapture-{seen,queue} directory layout are byte-
compatible with the bash version, so a live queue populated by the bash sweep
on a real machine keeps working after cutover. stdlib only.
"""
import json
import os
import time

import np_capture
import np_content
import np_evaluator
import np_toggle
import np_transcripts

# Transient capture failures (empty/non-JSON model output) release the claim so a
# later sweep retries; after this many failed passes we give up and mark the
# session permanently seen, so a genuinely un-capturable transcript can't burn a
# model call on every SessionStart forever.
_MAX_ATTEMPTS = 5


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


def _lock_path():
    return os.environ.get("BACKCAPTURE_LOCK") or os.path.join(
        _home(), ".cache", "nervepack", "backcapture-sweep.lock")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # e.g. EPERM (owned by another user) -- assume alive, don't steal it
    return True


def _acquire_lock(path):
    """One sweep at a time, system-wide. Returns False (never blocks/raises) if
    another live sweep already holds it -- caller must fail open, per invariant 1."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return True  # can't even make the cache dir -- fail open rather than block
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        pass
    except OSError:
        return True  # unexpected lock-file error -- fail open
    try:
        with open(path, encoding="utf-8") as fh:
            held_pid = int((fh.read() or "0").strip())
    except (OSError, ValueError):
        held_pid = 0
    if held_pid and _pid_alive(held_pid):
        return False
    try:  # stale lock (holder crashed/killed) -- reclaim once
        os.remove(path)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        return False  # lost the reclaim race to another sweep -- let it run


def _release_lock(path):
    try:
        os.remove(path)
    except OSError:
        pass


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


def _release_claim(seen_dir, sid):
    """Undo a _claim() so a later sweep can retry (used when capture failed
    transiently). The committed-metrics dedup + capture()'s own per-session
    marker keep a *successful* session from being re-captured after release."""
    try:
        os.remove(os.path.join(seen_dir, sid))
    except OSError:
        pass


def _bump_attempts(seen_dir, sid):
    """Increment and return the per-session transient-failure attempt count."""
    path = os.path.join(seen_dir, sid + ".attempts")
    try:
        n = int(open(path, encoding="utf-8").read() or "0")
    except (OSError, ValueError):
        n = 0
    n += 1
    try:
        os.makedirs(seen_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(n))
    except OSError:
        pass
    return n


def _clear_attempts(seen_dir, sid):
    try:
        os.remove(os.path.join(seen_dir, sid + ".attempts"))
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
            cwd = np_transcripts.extract_cwd(tpath) or _home()
            _write_queue_file(queue_file, sid, mt, tpath, cwd)


def _process(queue_dir, seen_dir, metrics_path, max_per_sweep, capture_fn, evaluate_fn,
             capture_ok_fn):
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
        # Keep the permanent claim only if capture actually recorded a note (or a
        # metrics row already exists). On a transient failure (model returned
        # empty/non-JSON), release the claim so a later sweep retries -- up to
        # _MAX_ATTEMPTS, after which we give up and leave the claim in place.
        # Previously the claim was written unconditionally before capture, so a
        # single transient failure dropped the session forever (#168).
        if capture_ok_fn(payload) or _already_in_metrics(sid, metrics_path):
            _clear_attempts(seen_dir, sid)
            processed += 1
            _log("back-captured %s (project %s)" % (sid, os.path.basename(cwd)))
        elif _bump_attempts(seen_dir, sid) >= _MAX_ATTEMPTS:
            _log("gave up on %s after %d capture attempts (still queued->seen)" % (sid, _MAX_ATTEMPTS))
        else:
            _release_claim(seen_dir, sid)
            _log("retry-queued %s (transient capture failure)" % sid)
    return processed


def run(payload_text, capture_fn=None, evaluate_fn=None, capture_ok_fn=None):
    """Entry point called by cli.py. `capture_fn`/`evaluate_fn` default to the
    real np_capture.capture / np_evaluator.evaluate; tests inject stubs."""
    if os.environ.get("NERVEPACK_AGENT"):        # re-entry guard — invariant 2
        return
    if not np_toggle.enabled("memory.backcapture"):
        return

    projects_dir = _projects_dir()
    if not os.path.isdir(projects_dir):
        return

    lock_path = _lock_path()
    if not _acquire_lock(lock_path):
        _log("sweep skipped: another sweep already running")
        return

    try:
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
                              capture_fn or np_capture.capture, evaluate_fn or np_evaluator.evaluate,
                              capture_ok_fn or np_capture.was_captured)

        if processed > 0:
            pending = 0
            try:
                names = os.listdir(queue_dir)
            except OSError:
                names = []
            for name in names:
                if os.path.isfile(os.path.join(queue_dir, name)) and not os.path.exists(
                        os.path.join(seen_dir, name)):
                    pending += 1
            _log("sweep done: %d session(s) captured, %d still queued" % (processed, pending))
    finally:
        _release_lock(lock_path)
