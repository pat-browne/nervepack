"""Bash-free port of np-dashboard-launch.sh's URL/opener resolution AND
open-dashboard.sh's manual on-demand open (open_manual()). The sole
implementation for both dashboard open paths: the SessionStart hook
(engine/nervepack_engine/hooks/open_dashboard.py, cli.py hook open-dashboard)
consumes dashboard_url()/resolve_opener()/boot_id() in-process, and the manual
open (cli.py open-dashboard) calls open_manual(). Both retired bash scripts
(np-dashboard-launch.sh, open-dashboard.sh) are gone.

boot_id() is a deliberate BEHAVIOR CHANGE from the bash original, not a
byte-parity port: bash's guard reads /proc/sys/kernel/random/boot_id, which
doesn't exist on macOS, so its `2>/dev/null || echo unknown` fallback made the
once-per-boot marker permanently "unknown" after the first session on any Mac
-- silently disabling dashboard auto-open forever, even across real reboots.
This port uses `sysctl -n kern.boottime` (verified present and correctly
reboot-sensitive on macOS) as the fallback instead, restoring the feature.

stdlib only.
"""
import os
import sys
# self-bootstrap (phase 20b-2): engine/setup holds np_paths, np_bashlib, the config
# files, and the stayed sibling modules; add it so this relocated module resolves them
# whether imported in-process or run standalone. Its own dir (nervepack_engine) is
# already on sys.path[0] when run directly, so moved-sibling imports resolve too.
_SETUP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "setup"))
if _SETUP not in sys.path:
    sys.path.insert(0, _SETUP)

import os
import shutil
import socket
import subprocess
import sys
import time

import np_paths
import np_toggle

_ENGINE = np_paths.REPO_ROOT  # the repo root (contains dashboard/, engine/, …)

_POLL_ATTEMPTS = 10
_POLL_INTERVAL = 0.2


def resolve_opener():
    """np_resolve_opener: explicit NP_DASH_OPENER override wins; else prefers
    xdg-open (Linux), falls back to open (macOS). "" if none available."""
    override = os.environ.get("NP_DASH_OPENER")
    if override:
        return override
    for candidate in ("xdg-open", "open"):
        if shutil.which(candidate):
            return candidate
    return ""


def is_listening(port, timeout=0.2):
    """np_dashboard_launch's _npd_listening: True if something accepts
    connections on 127.0.0.1:port right now."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def dashboard_url():
    """np_dashboard_url: file:// when evaluator.dashboard_serve is off; else
    ensures the local backend (np-dashboard-server.py) is listening on
    127.0.0.1:<dashboard_port>, spawning it (detached) if not yet up, polling
    briefly, and falling back to file:// if it never comes up. Fail-open."""
    if np_toggle.param("evaluator.dashboard_serve", "on") != "on":
        return "file://%s/dashboard/index.html" % _ENGINE

    try:
        port = int(np_toggle.param("evaluator.dashboard_port", "8787"))
    except ValueError:
        port = 8787
    top = np_toggle.param("evaluator.suggestions_top", "10")

    # Probe once and reuse the result -- a second probe against a listener
    # that's already up but hasn't accept()ed yet can exhaust its backlog
    # (observed on macOS with a bare, non-accepting listen() socket) and
    # time out, so only re-probe when we actually attempted a spawn.
    listening = is_listening(port)
    if not listening:
        server = os.path.join(np_paths.SETUP_DIR, "np-dashboard-server.py")
        env = dict(os.environ)
        env["NP_DASH_PORT"] = str(port)
        env["NP_SUGGESTIONS_TOP"] = str(top)
        try:
            subprocess.Popen(
                ["python3", server], env=env, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        for _ in range(_POLL_ATTEMPTS):
            listening = is_listening(port)
            if listening:
                break
            time.sleep(_POLL_INTERVAL)

    if listening:
        return "http://127.0.0.1:%d/" % port
    return "file://%s/dashboard/index.html" % _ENGINE


def boot_id():
    """Deliberate behavior change from bash -- see module docstring. Linux:
    /proc/sys/kernel/random/boot_id. macOS: sysctl -n kern.boottime (real,
    reboot-sensitive, unlike bash's permanent "unknown" fallback). "unknown"
    if neither is available."""
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as fh:
            got = fh.read().strip()
            if got:
                return got
    except OSError:
        pass
    try:
        result = subprocess.run(["sysctl", "-n", "kern.boottime"],
                                capture_output=True, text=True, timeout=1)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def open_manual():
    """Port of open-dashboard.sh: the MANUAL, on-demand dashboard open. Unlike
    the SessionStart hook (open once per OS boot), this is a deliberate user
    action with NO boot guard -- it always rebuilds the data file and opens. A
    single manual open is not in the SessionStart path, so it cannot start the
    remote-desktop reconnect/re-open loop the hook guards against. Fail-open:
    ALWAYS returns 0, never hard-errors.

    Mirrors the bash exactly: (1) refresh metrics.js (best-effort), passing the
    evaluator.wiki_nav/wiki_mermaid params build.py reads so the left-nav honors
    them; (2) resolve the URL via dashboard_url() (file:// by default, http:// +
    a spawned server when evaluator.dashboard_serve is on); (3) `command -v`
    gate -- if the resolved opener is neither on PATH (shutil.which) nor an
    existing path (os.path.isfile), print `no opener (<opener|none>) found` to
    stderr and return (a bogus NP_DASH_OPENER override still fails this gate);
    (4) else open it (best-effort) and print `opened <url>` to stdout."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(newline="\n")
        except (ValueError, OSError):
            pass

    env = dict(os.environ)
    env["WIKI_NAV"] = np_toggle.param("evaluator.wiki_nav", "on")
    env["WIKI_MERMAID"] = np_toggle.param("evaluator.wiki_mermaid", "on")
    build = os.path.join(_ENGINE, "dashboard", "build.py")
    try:
        subprocess.run([sys.executable, build], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass

    url = dashboard_url()

    opener = resolve_opener()
    if not (opener and (shutil.which(opener) or os.path.isfile(opener))):
        sys.stderr.write("no opener (%s) found\n" % (opener or "none"))
        return 0

    try:
        subprocess.run([opener, url], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass
    sys.stdout.write("opened %s\n" % url)
    return 0
