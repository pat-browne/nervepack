"""Shared subprocess seam for `np-llm.sh agent --tools "..."` -- the backend-
neutral agentic-call contract every ported maintenance cron needs (skill-
maintain's Sonnet pass in Phase 10; the future 71/72/76/77 ports). np-llm.sh
itself stays bash (it's the model/backend abstraction layer, out of scope for
this migration until every caller has moved off it) -- this module's job is
just to invoke it correctly and repeatably: prompt piped via stdin, `--tools`
space-joined, and -- critically for any multi-repo caller -- the subprocess
runs with its cwd set to whatever the caller requests, never hardcoded to the
engine root. Fail-open: any subprocess/OS error returns False, never raises.
"""
import os
import subprocess

import np_bashlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_NP_LLM_PATH = os.path.join(_HERE, "np-llm.sh")


def run_agent(prompt, tools, cwd=None):
    """Invoke `np-llm.sh agent --tools <tools>` with `prompt` on stdin, cd'd
    into `cwd` (defaults to the caller's current directory). Returns True iff
    the subprocess exited 0; never raises."""
    try:
        result = subprocess.run(
            np_bashlib.argv(["bash", _NP_LLM_PATH, "agent", "--tools", tools]),
            input=prompt, cwd=cwd, text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except OSError:
        return False
