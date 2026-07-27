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


def run_agent(prompt, tools, cwd=None, timeout=None):
    """Invoke np_model.agent() with `prompt`, `tools`, cd'd into `cwd` (defaults
    to the caller's current directory), bounded by `timeout` seconds (None = no
    bound). Returns True iff it exited 0; never raises."""
    try:
        returncode, _out, _err = np_model.agent(prompt, tools, cwd=cwd, timeout=timeout)
        return returncode == 0
    except (OSError, ValueError):
        return False
