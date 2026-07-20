"""Bash-free port of episodic-recall.sh — UserPromptSubmit hook: on a
session's first N prompts, inject episodic themes matching the prompt as
low-authority background context. Keyword-only (no LLM call). Fail-open:
returns "" on any early-exit path.

Uses np_content.merge_roots()/merge_mode() (not np-layer-lib.sh) and
np_episodic_match.match() (not episodic-match.sh) in-process to stay
bash-free. When pii_filter is on, shells to np-pii-filter.py via a
sys.executable subprocess (Python-to-Python, still bash-free) rather than
importing its private, hyphenated-filename internals — pii_filter_fn is
injectable for tests.
"""
import json
import os
import subprocess
import sys

import np_content
import np_episodic_match
import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))
_PII_FILTER_SCRIPT = os.path.normpath(os.path.join(_HERE, "..", "..", "setup", "np-pii-filter.py"))


def _max_prompts():
    try:
        return int(os.environ.get("EPISODIC_RECALL_MAX", "2"))
    except ValueError:
        return 2


def _top():
    try:
        return int(os.environ.get("EPISODIC_RECALL_TOP", "3"))
    except ValueError:
        return 3


def _state_dir():
    return os.environ.get("EPISODIC_STATE_DIR") or "/tmp/nervepack-episodic-recall"


def _layer_roots():
    override = os.environ.get("EPISODIC_DIR")
    if override:
        return [override], "override"
    roots = [os.path.join(r, "memory", "episodic") for r in np_content.merge_roots()]
    return roots, np_content.merge_mode()


def _default_pii_filter(text):
    try:
        result = subprocess.run(
            [sys.executable, _PII_FILTER_SCRIPT, "--mode", "fast"],
            input=text, capture_output=True, text=True,
        )
        return result.stdout if result.returncode == 0 else text
    except OSError:
        return text


def run(payload_text, pii_filter_fn=None):
    if not np_toggle.enabled("memory.recall"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    sid = payload.get("session_id") or "unknown"
    prompt = payload.get("prompt") or ""
    if not prompt:
        return ""

    ep_roots, mode = _layer_roots()
    if not any(os.path.isfile(os.path.join(d, "INDEX.md")) for d in ep_roots):
        return ""

    state_dir = _state_dir()
    try:
        os.makedirs(state_dir, exist_ok=True)
    except OSError:
        return ""
    counter = os.path.join(state_dir, sid.replace("/", "_"))
    try:
        with open(counter, encoding="utf-8") as fh:
            count = int(fh.read().strip() or "0")
    except (OSError, ValueError):
        count = 0
    if count >= _max_prompts():
        return ""
    try:
        with open(counter, "w", encoding="utf-8") as fh:
            fh.write(str(count + 1))
    except OSError:
        pass

    ctx = ("Episodic context (background — may be stale; durable skills/sources/wiki "
           "override). Consider whether each applies before acting. Matched themes from "
           "prior sessions:")
    emitted = []
    hit_any = False
    for d in ep_roots:
        index_path = os.path.join(d, "INDEX.md")
        if not os.path.isfile(index_path):
            continue
        topics = np_episodic_match.match(index_path, prompt)[:_top()]
        for t in topics:
            if mode == "override" and t in emitted:
                continue
            f = os.path.join(d, t + ".md")
            if not os.path.isfile(f):
                continue
            emitted.append(t)
            hit_any = True
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()[:40]
            except OSError:
                lines = []
            ctx += "\n\n" + "".join(lines).rstrip("\n")
    if not hit_any:
        return ""

    if np_toggle.enabled("pii_filter"):
        filt = pii_filter_fn or _default_pii_filter
        ctx = filt(ctx)

    np_toggle.signal(sid, "episodic-recall")

    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}},
        separators=(",", ":"))
