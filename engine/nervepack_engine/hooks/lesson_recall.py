"""Bash-free port of lesson-recall.sh — UserPromptSubmit hook: on a session's
first N prompts, inject lessons whose topic_triggers match the prompt.
Merge of the former playbook-recall.sh + strategy-recall.sh: framing branches
on each matched entry's `provenance` frontmatter (failure -> imperative "past
failure pattern"; success -> advisory "approach that worked"). A topic file
may carry BOTH provenances back to back -- each block surfaces with its own
framing. Also arms the marker lesson_guard.py's Phase 2 checks for, when a
matched failure-provenance lesson's file contains `tool_name_match` ANYWHERE
in the file (a plain whole-file check, intentionally NOT restricted to the
first frontmatter block -- see lesson_guard.py's module docstring for the
asymmetry this preserves). Fail-open: returns "" on any early-exit path.

Uses np_content.merge_roots()/merge_mode() in-process (never np-layer-lib.sh).
PII filtering shells to np-pii-filter.py via sys.executable (Python-to-Python,
still bash-free), matching episodic_recall.py's established pattern.
"""
import json
import os
import re
import subprocess
import sys

import np_content
import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))
_PII_FILTER_SCRIPT = os.path.normpath(os.path.join(_HERE, "..", "..", "setup", "np-pii-filter.py"))
_HEADER_RE = re.compile(r'^\*\*(Symptom|Why|Do|Avoid|Title|When):')
_TOOL_NAME_MATCH_RE = re.compile(r'^  tool_name_match:', re.MULTILINE)


def _max_prompts():
    try:
        return int(os.environ.get("EPISODIC_RECALL_MAX", "2"))
    except ValueError:
        return 2


def _state_dir():
    return os.environ.get("EPISODIC_STATE_DIR") or "/tmp/nervepack-playbook-recall"


def _layer_roots():
    override = os.environ.get("EPISODIC_LESSON_DIR")
    if override:
        return [override], "override"
    roots = [os.path.join(r, "memory", "lessons") for r in np_content.merge_roots()]
    return roots, np_content.merge_mode()


def _lesson_blocks(path):
    """Mirror bash's _ls_blocks: yield (provenance, body) per frontmatter+body
    block. A file has 1 block (single provenance) or 2 (merged playbook+
    strategy entry)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    c = 0
    prov = {}
    body = {}
    for line in lines:
        line = line.rstrip("\n")
        if line == "---":
            c += 1
            continue
        blk = (c + 1) // 2
        if blk < 1:
            continue
        if c % 2 == 1:
            if line.startswith("provenance:"):
                prov[blk] = line[len("provenance:"):].strip()
        else:
            if _HEADER_RE.match(line):
                body[blk] = body.get(blk, "") + line + " "
    result = []
    b = 1
    while b in prov:
        result.append((prov[b], body.get(b, "")))
        b += 1
    return result


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
    if not np_toggle.enabled("lessons"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    sid = payload.get("session_id") or "unknown"
    prompt = (payload.get("prompt") or "").lower()
    if not prompt:
        return ""

    ls_roots, mode = _layer_roots()
    if not any(os.path.isfile(os.path.join(d, "INDEX.md")) for d in ls_roots):
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

    fail_ctx = ""
    success_ctx = ""
    seen = []
    for d in ls_roots:
        index_path = os.path.join(d, "INDEX.md")
        if not os.path.isfile(index_path):
            continue
        try:
            with open(index_path, encoding="utf-8", errors="replace") as fh:
                index_lines = fh.readlines()
        except OSError:
            continue
        for line in index_lines:
            line = line.rstrip("\n")
            fields = line.split("|")
            if len(fields) < 5:
                continue
            topic = fields[1].strip()
            triggers = fields[4].strip()
            if not topic or topic == "topic":
                continue
            if re.match(r'^-+$', topic):
                continue
            if mode == "override" and topic in seen:
                continue
            hit = False
            for kw in triggers.split(","):
                kw = kw.strip().lower()
                if kw and kw in prompt:
                    hit = True
                    break
            if not hit:
                continue
            seen.append(topic)
            f = os.path.join(d, topic + ".md")
            if not os.path.isfile(f):
                continue
            for prov, body in _lesson_blocks(f):
                if prov == "failure":
                    fail_ctx += "[%s] %s\n" % (topic, body)
                    try:
                        with open(f, encoding="utf-8", errors="replace") as fh:
                            whole = fh.read()
                    except OSError:
                        whole = ""
                    if _TOOL_NAME_MATCH_RE.search(whole):
                        try:
                            os.makedirs(state_dir, exist_ok=True)
                            armed = os.path.join(state_dir, "%s-%s-gate-armed" % (
                                sid.replace("/", "_"), topic))
                            with open(armed, "a", encoding="utf-8"):
                                pass
                        except OSError:
                            pass
                elif prov == "success":
                    success_ctx += "[%s] %s\n" % (topic, body)

    ctx = ""
    if fail_ctx:
        ctx += "Before proceeding — past failure patterns apply (Nervepack lessons; apply the Do/Avoid):\n" + fail_ctx
    if success_ctx:
        ctx += "Approaches that worked before (Nervepack lessons) — consider whether each applies before acting:\n" + success_ctx
    if not ctx:
        return ""

    if np_toggle.enabled("pii_filter"):
        filt = pii_filter_fn or _default_pii_filter
        ctx = filt(ctx)

    np_toggle.signal(sid, "lesson-recall")

    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}},
        separators=(",", ":"))
