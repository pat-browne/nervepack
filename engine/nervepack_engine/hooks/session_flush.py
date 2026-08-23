"""Bash-free port of np-session-flush.sh -- SessionEnd hook that drains the
capture/evaluator inboxes into committed layers immediately, so the daily/weekly
crons are a backup, not the only path. Two load-bearing properties, unchanged
from the bash original:
  - The NERVEPACK_AGENT re-entry guard is enforced generically at cli.py's
    dispatch layer (not duplicated here) -- step 2 below runs `claude -p`,
    which re-fires SessionEnd, so the guard matters, but it's already checked
    before this function is ever called.
  - DETACH: the maintain step takes ~30-60s; without detaching, session exit
    would block on it and Claude Code would cancel the hook for overrunning
    its budget. Detachment uses subprocess.Popen(start_new_session=True) -- a
    single cross-platform path (see this phase's plan for why the bash
    original's Linux-setsid-vs-macOS-nohup+disown branch collapses to one).

Both substeps are now Python: aggregate-metrics is np_aggregate.py, invoked via
[sys.executable, path]; episodic-maintain is np_agentic_cron.py's
episodic_maintain(), invoked the same way with its cron name appended (that
module's __main__ dispatches by name, mirroring cli.py's own _CRONS table) --
its bash original, 72-run-episodic-maintain.sh, is retired. Each still runs
out-of-process (not imported and called in-line) so a substep crash/hang can't
take down the detached flush process itself.

step_fns is injectable for tests (defaults to the two real substeps, both Python).
NP_FLUSH_NODETACH keeps it foreground for tests, matching the bash original's
env var name exactly. NP_FLUSH_DETACHED is the internal re-entry marker set on
the detached re-exec (also unchanged from the bash original's name/meaning).
NP_FLUSH_NO_SETSID (the bash original's Linux-CI-exercises-the-macOS-fallback
knob) has NO Python equivalent -- there's only one code path now, so there's
nothing to force.
"""
import os
import subprocess
import sys
import time
import np_dirs

import np_toggle          # resolved via cli.py's sys.path setup, as in the sibling hooks

_ENGINE_SETUP_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "setup"))
_CLI_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cli.py"))
_ARG_SEP = "\x1c"  # embeds a standalone-entrypoint arg in a _STEP_PATHS entry
                    # without colliding with os.pathsep (see NP_FLUSH_STEP_PATHS
                    # round-trip below) or any real filesystem path character.
_STEP_PATHS = [
    os.path.join(_ENGINE_SETUP_DIR, "np_aggregate.py"),
    os.path.join(_ENGINE_SETUP_DIR, "np_agentic_cron.py") + _ARG_SEP + "episodic-maintain",
]


def _log_path():
    return os.environ.get("SESSION_FLUSH_LOG") or np_dirs.cache_path("session-flush.log")


def _log(msg):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fh.write("%s %s\n" % (ts, msg))
    except OSError:
        pass


def _stamp_path():
    return os.environ.get("SESSION_FLUSH_STAMP") or np_dirs.cache_path("last-flush")


def _lock_path():
    return os.environ.get("SESSION_FLUSH_LOCK") or np_dirs.cache_path("session-flush.lock")


def _throttle_ok():
    """True (and stamps) iff at least memory.flush_interval has passed since the
    last flush. SessionEnd fires far more often than there is work to drain --
    unthrottled it ran ~640x/day (#202). The daily/weekly crons remain the
    backstop, so a skipped flush only delays promotion, never drops it."""
    try:
        interval = int(np_toggle.param("memory.flush_interval", "900") or "900")
    except ValueError:
        interval = 900
    stamp = _stamp_path()
    try:
        last = int((open(stamp, encoding="utf-8").read().strip() or "0"))
    except (OSError, ValueError):
        last = 0
    age = int(time.time()) - last
    if last and age < interval:
        _log("skip: within %ds flush interval (age %ds)" % (interval, age))
        return False
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))
    except OSError:
        pass                                   # fail open: an unstampable flush still runs
    return True


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _acquire_lock(path):
    """One flush at a time. Both substeps commit into a shared git working tree,
    so concurrent flushes are a multi-writer hazard (AGENTS.md "concurrent
    session"). Fail open on any unexpected error -- never block the hook."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return True
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        pass
    except OSError:
        return True
    try:
        with open(path, encoding="utf-8") as fh:
            held = int((fh.read() or "0").strip())
    except (OSError, ValueError):
        held = 0
    if held and _pid_alive(held):
        return False
    try:                                       # stale lock -- reclaim once
        os.remove(path)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        return False                           # lost the reclaim race -- let the winner run


def _release_lock(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _default_step_fn(path):
    def _call():
        # Both real substeps (np_aggregate.py, np_agentic_cron.py) run in their own
        # interpreter here rather than in-process, so a substep failure/crash still
        # can't take down the detached flush process. A `path` may carry an extra
        # standalone-entrypoint arg after _ARG_SEP (e.g. "np_agentic_cron.py\x1c
        # episodic-maintain") -- harmless no-op split for a bare path. Every substep
        # is a .py entrypoint (no bash substep exists), so it runs via the interpreter.
        target, _, arg = path.partition(_ARG_SEP)
        argv = [sys.executable, target] + ([arg] if arg else [])
        subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return _call


def run(payload_text, step_fns=None):
    # Throttle in the PARENT only: the detached child re-enters run() and would
    # otherwise be blocked by the stamp its own parent just wrote. Checking here
    # also means a throttled flush never pays for the fork.
    if not os.environ.get("NP_FLUSH_DETACHED") and not _throttle_ok():
        return ""
    if not os.environ.get("NP_FLUSH_DETACHED") and os.environ.get("NP_FLUSH_NODETACH") != "1":
        env = dict(os.environ)
        env["NP_FLUSH_DETACHED"] = "1"
        # Carry the current _STEP_PATHS across the re-exec explicitly (rather than
        # letting the freshly-spawned interpreter re-derive its own module-level
        # default) so a test process that has swapped _STEP_PATHS (e.g. to stub
        # scripts) genuinely proves the detached child ran THOSE scripts, not the
        # real ones -- a real, unmocked subprocess.Popen still detaches and
        # completes real work, it's just told which scripts that work is.
        env["NP_FLUSH_STEP_PATHS"] = os.pathsep.join(_STEP_PATHS)
        try:
            subprocess.Popen(
                [sys.executable, _CLI_PATH, "hook", "session-flush"],
                env=env, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        return ""

    lock = _lock_path()
    if not _acquire_lock(lock):
        _log("skip: another flush is already running")
        return ""

    _log("flush start")
    try:
        if step_fns is not None:
            fns = step_fns
        else:
            override = os.environ.get("NP_FLUSH_STEP_PATHS")
            paths = override.split(os.pathsep) if override else _STEP_PATHS
            fns = [_default_step_fn(p) for p in paths]
        for fn in fns:
            try:
                fn()
            except Exception:
                pass
        _log("flush done")
    finally:
        _release_lock(lock)
    return ""
