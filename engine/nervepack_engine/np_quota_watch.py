"""Detect a Claude usage-limit violation and schedule a resume nudge.

The `quota-detect` Stop hook fires the check after every turn. The
`quota-watch` cron re-runs it every 30 minutes as a backstop.

Signal: Claude Code logs `Claude AI usage limit reached|<unix_ts>`, the
API's own reset time, when it gets rate-limited.

Resume: a desktop notification one minute after reset, telling the human
to type "continue". No tmux or headless injection.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

_SETUP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import np_dirs  # noqa: E402
import np_host  # noqa: E402
import np_toggle  # noqa: E402

# Claude Code's own literal message: "Claude AI usage limit reached|1717027200".
_LIMIT_RE = re.compile(r"usage limit reached\|(\d{9,13})", re.I)

_RESUME_DELAY_S_DEFAULT = 60  # "1 minute after that time" (user's spec, verbatim)
_STATE_FILE = "quota-watch-state.json"


def _state_path():
    return np_dirs.cache_path(_STATE_FILE)


def _load_state():
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
    except OSError:
        pass


def _epoch_ms_to_s(ts):
    """A 13-digit value is milliseconds. A 9-10 digit value is seconds."""
    return ts / 1000.0 if ts > 10_000_000_000 else float(ts)


def find_reset_epoch(text):
    """Latest usage-limit reset epoch (seconds) found in text, or None."""
    matches = _LIMIT_RE.findall(text or "")
    if not matches:
        return None
    return _epoch_ms_to_s(int(matches[-1]))


def _notify(message):
    """Best-effort desktop notification. Never raises."""
    candidates = (
        ["notify-send", "-u", "critical", "nervepack: quota reset", message],
        ["osascript", "-e", 'display notification "%s" with title "nervepack: quota reset"' % message],
    )
    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=False, timeout=10)
                return True
            except (OSError, subprocess.SubprocessError):
                continue
    return False


def _log(msg):
    try:
        path = np_dirs.cache_path("quota-watch.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg))
    except OSError:
        pass


def _schedule_at(resume_epoch):
    """Schedule a one-shot `at` job that notifies at resume_epoch.

    Returns True if scheduled, False if `at` isn't installed (the 30-min
    cron covers the miss instead).
    """
    if not shutil.which("at"):
        _log("`at` not installed -- falling back to cron-only detection")
        return False
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
    cmd = "%s %s cron quota-notify" % (sys.executable, cli)
    when = time.strftime("%H:%M %Y-%m-%d", time.localtime(resume_epoch))
    try:
        subprocess.run(["at", when], input=cmd + "\n", text=True,
                        capture_output=True, timeout=10, check=True)
        _log("scheduled `at` job for %s" % when)
        return True
    except (OSError, subprocess.SubprocessError):
        _log("failed to schedule `at` job for %s" % when)
        return False


def _resume_delay_s():
    try:
        return int(np_toggle.param("quota_watch.resume_delay_s", str(_RESUME_DELAY_S_DEFAULT)))
    except (TypeError, ValueError):
        return _RESUME_DELAY_S_DEFAULT


def detect_and_schedule(text, source):
    """Scan text for the usage-limit message and schedule a resume nudge.

    No-op if quota_watch is toggled off, or this reset time is already
    scheduled. Returns a short status string. Never raises.
    """
    if not np_toggle.enabled("quota_watch"):
        return "skipped: quota_watch disabled"

    reset_epoch = find_reset_epoch(text)
    if reset_epoch is None:
        return "no signal"

    state = _load_state()
    if state.get("reset_epoch") == reset_epoch and state.get("scheduled"):
        return "already scheduled"

    resume_epoch = reset_epoch + _resume_delay_s()
    scheduled = _schedule_at(resume_epoch)
    state.update({
        "reset_epoch": reset_epoch,
        "resume_epoch": resume_epoch,
        "detected_at": time.time(),
        "source": source,
        "scheduled": scheduled,
        "notified": False,
    })
    _save_state(state)
    _log("detected via %s -- reset %s, nudge at %s (at-scheduled=%s)"
         % (source, time.ctime(reset_epoch), time.ctime(resume_epoch), scheduled))
    return "scheduled" if scheduled else "recorded (no at)"


def notify_now():
    """Fire the resume notification.

    Called by the `at` job, and by the cron fallback once resume_epoch has
    passed without a notification having gone out.
    """
    state = _load_state()
    resume_epoch = state.get("resume_epoch")
    if not resume_epoch or state.get("notified"):
        return "nothing to notify"
    _notify('Your claude.ai usage limit has reset. Type "continue" to resume.')
    state["notified"] = True
    _save_state(state)
    _log("notified: quota reset, resume nudge sent")
    return "notified"


def _recent_transcripts(within_s):
    cutoff = time.time() - within_s
    for path in glob.glob(os.path.join(np_host.transcripts_dir(), "*", "*.jsonl")):
        try:
            if os.path.getmtime(path) >= cutoff:
                yield path
        except OSError:
            continue


def cron_scan():
    """`quota-watch` cron entrypoint, run every 30 minutes.

    Scans transcripts touched in the last 35 minutes for the usage-limit
    signal, and fires an overdue resume notification if the `at` job never
    ran. Never raises.
    """
    paths = list(_recent_transcripts(35 * 60))
    found = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        status = detect_and_schedule(text, "cron:%s" % os.path.basename(path))
        if status in ("scheduled", "recorded (no at)"):
            found += 1

    state = _load_state()
    resume_epoch = state.get("resume_epoch")
    if resume_epoch and not state.get("notified") and time.time() >= resume_epoch:
        notify_now()

    return "ok: scanned %d recent transcript(s), %d new detection(s)" % (len(paths), found)


if __name__ == "__main__":
    print(cron_scan())
