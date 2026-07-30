"""Shared seam for the backend-neutral agentic-call contract every maintenance
cron needs (skill-maintain's Sonnet pass, memory-promote/refine/compact). This calls
np_model.agent() in-process -- np_model.py is the sole model seam (phase 9
ported `agent` in-process; phase 19 retired the old bash wrapper `np-llm.sh`).
This module's job is just to invoke it correctly and repeatably: prompt piped
via stdin, `--tools` space-joined, and -- critically for any multi-repo
caller -- the call runs with its cwd set to whatever the caller requests,
never hardcoded to the engine root. Fail-open: any subprocess/OS error or
non-zero exit returns False, never raises.
"""
import os
import sys
# self-bootstrap (phase 20b-2): np_toggle/np_content/np_model and the other library
# modules were relocated into engine/nervepack_engine/; add that package dir so this
# script's flat imports of them resolve whether run standalone or imported.
_ENGINE_PKG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nervepack_engine"))
if _ENGINE_PKG not in sys.path:
    sys.path.insert(0, _ENGINE_PKG)

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import np_model  # noqa: E402


def _append(log_path, *chunks):
    """Append the agent's own output to the caller's cron log, mirroring the
    retired bash bodies' `>> "$LOG" 2>&1`. Best-effort: logging must never break
    a maintenance run (ARCHITECTURE invariant 1)."""
    text = "".join(c for c in chunks if c)
    if not text:
        return
    try:
        parent = os.path.dirname(log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
    except OSError:
        pass


def run_agent(prompt, tools, cwd=None, timeout=None, log_path=None):
    """Invoke np_model.agent() with `prompt`, `tools`, cd'd into `cwd` (defaults
    to the caller's current directory), bounded by `timeout` seconds (None = no
    bound). Returns True iff it exited 0. Raises only np_model.AuthError: auth is
    not a run outcome, and returning False would file it under "the agent tried
    and failed", which is what kept #201 invisible for two weeks.

    `log_path` (optional): append the agent's stdout+stderr there. The bash cron
    bodies this replaced ended `... | np-llm.sh agent ... >> "$LOG" 2>&1`, so the
    maintenance agent's report — and any error it printed — landed in the cron
    log. The phase-9 port dropped both, leaving every run as a bare
    `=== <name> run ===` header: a healthy run and a dead one looked identical,
    which is how ~a week of no-op memory-promote runs went unnoticed. Callers
    that own a log should pass it."""
    try:
        returncode, out, err = np_model.agent(prompt, tools, cwd=cwd, timeout=timeout)
    except np_model.AuthError as exc:
        if log_path:
            _append(log_path, "", "auth failed: %s\n" % exc)
        raise
    except (OSError, ValueError):
        return False
    if log_path:
        _append(log_path, out, err)
    return returncode == 0
