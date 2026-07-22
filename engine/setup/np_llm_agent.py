"""Shared seam for the backend-neutral agentic-call contract every maintenance
cron needs (skill-maintain's Sonnet pass, memory-promote/refine/compact). As of
phase 9 of the bash->Python CLI consolidation (content overlay spec
2026-07-15-nervepack-python-cli-consolidation-design.md), this calls
np_model.agent() in-process -- no more shelling to bash `np-llm.sh agent`.
This module's job is just to invoke it correctly and repeatably: prompt piped
via stdin, `--tools` space-joined, and -- critically for any multi-repo
caller -- the call runs with its cwd set to whatever the caller requests,
never hardcoded to the engine root. Fail-open: any subprocess/OS error or
non-zero exit returns False, never raises.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import np_model  # noqa: E402


def run_agent(prompt, tools, cwd=None):
    """Invoke np_model.agent() with `prompt`, `tools`, cd'd into `cwd` (defaults
    to the caller's current directory). Returns True iff it exited 0; never
    raises."""
    try:
        returncode, _out, _err = np_model.agent(prompt, tools, cwd=cwd)
        return returncode == 0
    except (OSError, ValueError):
        return False
