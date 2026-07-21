"""Bash-free port of np-dashboard-launch.sh's URL/opener resolution. Consumed
in-process by the new engine/nervepack_engine/hooks/open_dashboard.py
(cli.py-dispatched SessionStart hook). np-dashboard-launch.sh itself is NOT
retired -- open-dashboard.sh (the manual open script, out of scope for this
migration phase) still sources it directly, so both implementations coexist.

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
import shutil
import socket
import subprocess
import time

import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))
_ENGINE = os.path.dirname(os.path.dirname(_HERE))  # engine/setup -> engine -> repo root

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
        server = os.path.join(_HERE, "np-dashboard-server.py")
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
