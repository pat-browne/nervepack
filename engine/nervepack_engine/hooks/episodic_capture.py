"""Thin cli.py-dispatched wrapper around the already-existing, already-tested
np_capture.capture() -- the in-process Python port of episodic-capture.sh's
orchestration. Registered on BOTH SessionEnd ("session-end", the default) and
PreCompact ("checkpoint"), which is why this hook, uniquely among the hooks
ported so far, accepts a second positional argument: cli.py's argv-passthrough
(Task 1 of this phase) forwards it from `cli.py hook episodic-capture <mode>`.

capture_fn is injectable for tests, mirroring backcapture_sweep.py's own
capture_fn/evaluate_fn seam for calling this exact function. The bash original
never wrote to stdout (side-effect only, via the inbox/log) -- this always
returns "" regardless of capture()'s internal status string.
"""
import json

import np_capture


def run(payload_text, mode="session-end", capture_fn=None):
    capture_fn = capture_fn or np_capture.capture
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        payload = {}
    try:
        capture_fn(payload, mode)
    except Exception:
        pass
    return ""
