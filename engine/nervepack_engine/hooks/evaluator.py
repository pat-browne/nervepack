"""Thin cli.py-dispatched wrapper around the already-existing, already-tested
np_evaluator.evaluate() -- the in-process Python port of np-evaluator.sh's
orchestration. Registered on SessionEnd only (no mode concept, unlike
episodic_capture.py). evaluate_fn is injectable for tests, mirroring
backcapture_sweep.py's own evaluate_fn seam. The bash original never wrote to
stdout -- this always returns "" regardless of evaluate()'s internal status
string.
"""
import json

import np_evaluator


def run(payload_text, evaluate_fn=None):
    evaluate_fn = evaluate_fn or np_evaluator.evaluate
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        payload = {}
    try:
        evaluate_fn(payload)
    except Exception:
        pass
    return ""
