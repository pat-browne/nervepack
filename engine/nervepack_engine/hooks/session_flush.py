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
    return os.environ.get("SESSION_FLUSH_LOG") or os.path.join(
        os.environ.get("HOME") or os.path.expanduser("~"), ".cache", "nervepack", "session-flush.log")


def _log(msg):
    try:
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fh.write("%s %s\n" % (ts, msg))
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

    _log("flush start")
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
    return ""
