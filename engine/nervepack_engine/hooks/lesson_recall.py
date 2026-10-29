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

Uses np_content.merge_roots()/merge_mode() in-process (the sole layer-stack
resolver since the sourced bash layer lib was retired in phase 18).
PII filtering shells to np-pii-filter.py via sys.executable (Python-to-Python,
still bash-free), matching episodic_recall.py's established pattern.
"""
import importlib.util
import json
import os
import re

import np_content
import np_recall_common
import np_toggle

_HEADER_RE = re.compile(r'^\*\*(Symptom|Why|Do|Avoid|Title|When):')
_TOOL_NAME_MATCH_RE = re.compile(r'^  tool_name_match:', re.MULTILINE)
_FORMAT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "setup", "np_lesson_format.py"))
_format_mod = None


def _format():
    """engine/setup/np_lesson_format.py (the paired-rule parser), loaded once.
    None when it can't load -- recall then falls back to legacy bodies only."""
    global _format_mod
    if _format_mod is None:
        try:
            spec = importlib.util.spec_from_file_location("np_lesson_format", _FORMAT_PATH)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _format_mod = mod
        except Exception:
            _format_mod = False
    return _format_mod or None


def _max_prompts():
    return np_recall_common.max_prompts()


def _norm(text):
    # Same normalization as np_episodic_match: lowercase, non-alnum runs -> one space.
    return " " + re.sub(r'[^a-z0-9]+', ' ', text.lower()) + " "


def _int_param(key, default):
    try:
        return int(np_toggle.param(key, str(default)))
    except ValueError:
        return default


def _min_hits():
    return _int_param("lessons.recall_min_hits", 1)


def _top():
    return _int_param("lessons.recall_top", 3)


def _state_dir():
    return os.environ.get("EPISODIC_STATE_DIR") or "/tmp/nervepack-playbook-recall"


def _counter_path(state_dir, sid):
    # Feature-namespaced ("ls-") so a shared EPISODIC_STATE_DIR override can't merge
    # the lesson- and episodic-recall per-session counters into ONE file. See
    # episodic_recall._counter_path (which uses "ep-"). (#171)
    return os.path.join(state_dir, "ls-" + sid.replace("/", "_"))


def _layer_roots():
    override = os.environ.get("EPISODIC_LESSON_DIR")
    if override:
        return [override], "override"
    roots = [os.path.join(r, "memory", "lessons") for r in np_content.merge_roots()]
    return roots, np_content.merge_mode()


def _lesson_blocks(path):
    """Mirror bash's _ls_blocks: yield (provenance, body, paired) per
    frontmatter+body block. A file has 1 block (single provenance) or 2 (merged playbook+
    strategy entry). A paired-rule body (spec 0093, paired=True) yields its
    rendered objective headings + rule lines; a legacy body yields its `**Header:**` lines (first
    line of each field only -- wrapped continuations are dropped, which is why
    legacy bodies are migrated)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    fmt = _format()
    if fmt is not None:
        result = []
        for block in fmt.parse(text):
            if not block.provenance:
                break  # same as the legacy reader: blocks stop at the first without provenance
            if block.rules:
                suffix = " (worked before)" if block.provenance == "success" else ""
                result.append((block.provenance, fmt.render(block, suffix), True))
            else:
                body = " ".join(block.legacy)
                result.append((block.provenance, body + " " if body else "", False))
        return result
    lines = text.splitlines(True)
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
        result.append((prov[b], body.get(b, ""), False))
        b += 1
    return result


def _arm_if_gated(f, state_dir, sid, topic):
    """Touch the marker lesson_guard.py checks when a failure lesson carries tool_name_match."""
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            whole = fh.read()
    except OSError:
        return
    if "provenance: failure" not in whole or not _TOOL_NAME_MATCH_RE.search(whole):
        return
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(os.path.join(state_dir, "%s-%s-gate-armed" % (sid.replace("/", "_"), topic)),
                  "a", encoding="utf-8"):
            pass
    except OSError:
        pass


def _default_pii_filter(text):
    return np_recall_common.default_pii_filter(text)


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
    counter = _counter_path(state_dir, sid)
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

    rule_ctx = ""
    fail_ctx = ""
    success_ctx = ""
    norm_prompt = _norm(prompt)
    candidates = []  # (score, specificity, order, topic, file)
    rows = []
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
            fields = line.rstrip("\n").split("|")
            if len(fields) < 5:
                continue
            topic = fields[1].strip()
            if not topic or topic == "topic" or re.match(r'^-+$', topic):
                continue
            kws = [_norm(kw).strip() for kw in fields[4].split(",")]
            rows.append((d, topic, [k for k in kws if k]))
    # Document frequency per trigger: a trigger many topics share is weak evidence.
    df = {}
    for _, _, kws in rows:
        for k in set(kws):
            df[k] = df.get(k, 0) + 1
    seen = []
    for order, (d, topic, kws) in enumerate(rows):
        if mode == "override" and topic in seen:
            continue
        # Whole-word match only: a substring hit ("ci" in "decision") is noise.
        hits = [k for k in set(kws) if (" " + k + " ") in norm_prompt]
        if len(hits) < _min_hits():
            continue
        seen.append(topic)
        spec = sum(1.0 / df[k] for k in hits)
        candidates.append((len(hits), spec, order, topic, os.path.join(d, topic + ".md")))
    candidates.sort(key=lambda c: (-c[0], -c[1], c[2]))
    # Arm the tool gate for every matched failure lesson, not only the injected top N,
    # so the cap never silently disables a lesson_guard check.
    for _, _, _, topic, f in candidates[_top():]:
        _arm_if_gated(f, state_dir, sid, topic)
    for _, _, _, topic, f in candidates[:_top()]:
        if not os.path.isfile(f):
            continue
        for prov, body, paired in _lesson_blocks(f):
            # Never inject a bare "[topic]" tag for a body recall can't read.
            entry = "[%s] %s\n" % (topic, body) if body.strip() else ""
            if paired:
                # A paired rule is self-framing (DON'T -> DO, when, why), so it
                # skips the legacy preamble and topic tag -- that keeps the
                # per-prompt cost at the rule itself (spec 0093).
                rule_ctx += body + "\n"
                entry = ""
            if prov == "failure":
                fail_ctx += entry
                _arm_if_gated(f, state_dir, sid, topic)
            elif prov == "success":
                success_ctx += entry

    ctx = rule_ctx
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
