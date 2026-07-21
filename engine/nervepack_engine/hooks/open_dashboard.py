"""Bash-free port of 74-open-dashboard.sh -- SessionStart hook that refreshes
metrics then opens the dashboard, ONCE per OS boot (see np_dashboard.boot_id()
for the deliberate macOS behavior-change note). Fail-open throughout: this must
never block or break session startup. aggregate_fn/opener_fn are injectable
for tests (aggregate_fn defaults to a subprocess call to np_aggregate.py, the
retired 73-aggregate-metrics.sh's Python replacement; opener_fn defaults
to a real subprocess call to the resolved opener).
"""
import os
import subprocess
import sys

import np_dashboard
import np_toggle

_ENGINE_SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINE_SETUP_DIR = os.path.normpath(os.path.join(_ENGINE_SETUP_DIR, "..", "..", "setup"))
_AGGREGATE_SCRIPT = os.path.join(_ENGINE_SETUP_DIR, "np_aggregate.py")


def _default_aggregate():
    try:
        subprocess.run([sys.executable, _AGGREGATE_SCRIPT],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass


def _default_opener(url):
    opener = np_dashboard.resolve_opener()
    if not opener:
        return
    try:
        subprocess.run([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass


def run(payload_text, aggregate_fn=None, opener_fn=None):
    if np_toggle.param("evaluator.dashboard_open", "on") != "on":
        return ""

    marker = os.environ.get("NP_DASH_MARKER") or os.path.join(
        os.environ.get("HOME") or os.path.expanduser("~"), ".cache", "nervepack", "dashboard-open-boot")
    boot = np_dashboard.boot_id()
    try:
        with open(marker, encoding="utf-8") as fh:
            if fh.read() == boot:
                return ""
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(boot)
    except OSError:
        pass

    try:
        (aggregate_fn or _default_aggregate)()
    except Exception:
        pass

    # Gate on a resolvable opener BEFORE calling opener_fn -- this must hold
    # even when opener_fn is test-injected (not just the real _default_opener),
    # so "no opener available" fails open regardless of which opener callable
    # is in play.
    if not np_dashboard.resolve_opener():
        return ""

    try:
        url = np_dashboard.dashboard_url()
    except Exception:
        return ""
    try:
        (opener_fn or _default_opener)(url)
    except Exception:
        pass
    return ""
