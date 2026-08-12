"""Bash-free port of lesson-guard.sh — PreToolUse hook: match the imminent
command/tool against enforced lesson patterns.

Phase 1: Bash command vs INDEX.md tool_match (gate=ask -> confirm; gate=warn
-> inject). Phase 2: non-Bash tool_name vs an armed marker (written by
lesson-recall.py) + the lesson file's FIRST frontmatter block's
enforce.tool_name_match/gate. Only enforced (provenance: failure) lessons
carry a non-empty tool_match / an enforce block; advisory (provenance:
success) lessons are skipped (empty tool_match cell = advisory-only skip).
Fail-open: returns "" on any early-exit path.

Phase 2's tool_name_match is matched as an (unanchored-by-caller) regex via
`re.fullmatch` -- mirroring Phase 1's `re.search(tool_match, cmd)` -- rather
than a plain string equality. A literal tool name (`"Read"`, `"Edit"`) still
matches exactly (fullmatch of a literal against itself == equality), but a
lesson can now also express an alternation (e.g.
`"^(Edit|Write|mcp__.*__(repo_create_pull_request|repo_reply_to_comment))$"`)
to cover a family of tool names in one entry -- needed because MCP tool names
embed a server id that varies by plugin/version (`mcp__<server>__<tool>`), so
a single exact string can't durably target "any PR-writing MCP tool." Invalid
regex fails open (skip), matching Phase 1's `except re.error: continue`.
This requires `hooks.manifest` to actually register a PreToolUse matcher that
makes Claude Code invoke this hook for the tool in question in the first
place (e.g. `Edit`, `Write`, `Skill`, or a broad `mcp__.*` catch-all) --
Phase 2 firing is necessary but not sufficient without that registration.

IMPORTANT asymmetry preserved from bash: this module's frontmatter read
(_first_block_value) looks ONLY at the file's first `---...---` block --
mirrors bash's awk `_fm_val` which exits after the second `---`. This is
DIFFERENT from lesson_recall.py's arming check, which is a whole-file grep
not restricted to the first block -- that asymmetry is intentional and
preserved, not a bug to fix here.
"""
import hashlib
import json
import os
import re

import np_content
import np_toggle

_HEADER_RE = re.compile(r'^\*\*(Symptom|Why|Do|Avoid|Title|When):')


def _lesson_dir():
    override = os.environ.get("EPISODIC_LESSON_DIR")
    if override:
        return override
    return np_content.layer_dir("lessons")


def _state_dir():
    return os.environ.get("EPISODIC_STATE_DIR") or "/tmp/nervepack-playbook-recall"


def _fingerprint(text):
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _lesson_body(lesson_dir, topic):
    f = os.path.join(lesson_dir, topic + ".md")
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip("\n") for ln in fh if _HEADER_RE.match(ln)]
    except OSError:
        lines = []
    body = " ".join(lines)
    return body if body else "See lessons/%s.md" % topic


def _first_block_value(path, key):
    """Mirror bash's _fm_val: scan ONLY the first `---...---` block (2-space
    indented `key:` line inside it), stop at the second `---`."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    c = 0
    pat = re.compile(r'^  ' + re.escape(key) + r':\s*(.*)$')
    for line in lines:
        line = line.rstrip("\n")
        if line == "---":
            c += 1
            if c == 2:
                break
            continue
        if c == 1:
            m = pat.match(line)
            if m:
                return m.group(1).strip().strip('"')
    return ""


def _fire_gate(sid, lesson_dir, cmd_or_tool_key, gate, topic):
    body = _lesson_body(lesson_dir, topic)
    fp = _fingerprint(cmd_or_tool_key)
    np_toggle.signal(sid, "lesson-guard %s %s :: %s" % (gate, topic, fp))
    if gate == "ask":
        reason = "Nervepack lesson '%s': %s" % (topic, body)
        return json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }}, separators=(",", ":"))
    ctx = "Nervepack lesson '%s' (past failure pattern): %s" % (topic, body)
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "additionalContext": ctx,
    }}, separators=(",", ":"))


def run(payload_text):
    if not np_toggle.enabled("lessons"):
        return ""
    if np_toggle.param("lessons.enforce", "on") != "on":
        return ""

    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""

    lesson_dir = _lesson_dir()
    index_path = os.path.join(lesson_dir, "INDEX.md")
    if not os.path.isfile(index_path):
        return ""

    tool_input = payload.get("tool_input") or {}
    cmd = tool_input.get("command") or ""
    tool_name = payload.get("tool_name") or ""
    file_path = tool_input.get("file_path") or ""
    sid = payload.get("session_id") or "unknown"

    # Phase 1: Bash command vs INDEX.md tool_match patterns.
    if cmd:
        try:
            with open(index_path, encoding="utf-8", errors="replace") as fh:
                index_lines = fh.readlines()
        except OSError:
            index_lines = []
        for line in index_lines:
            line = line.rstrip("\n")
            fields = line.split("|")
            if len(fields) < 4:
                continue
            topic = fields[1].strip()
            tool_match = fields[2].strip()
            gate = fields[3].strip()
            if not topic or topic == "topic":
                continue
            if re.match(r'^-+$', topic):
                continue
            if not tool_match:
                continue  # advisory-only lesson (no enforce)
            try:
                if re.search(tool_match, cmd):
                    return _fire_gate(sid, lesson_dir, cmd, gate, topic)
            except re.error:
                continue

    # Phase 2: non-Bash tool_name matching via armed marker + first-block frontmatter.
    if tool_name and tool_name != "Bash":
        state_dir = _state_dir()
        try:
            names = sorted(os.listdir(lesson_dir))
        except OSError:
            names = []
        for name in names:
            if name == "INDEX.md" or not name.endswith(".md"):
                continue
            f = os.path.join(lesson_dir, name)
            tnm = _first_block_value(f, "tool_name_match")
            if not tnm:
                continue
            try:
                if not re.fullmatch(tnm, tool_name):
                    continue
            except re.error:
                continue
            topic = name[:-3]
            armed = os.path.join(state_dir, "%s-%s-gate-armed" % (sid.replace("/", "_"), topic))
            if not os.path.exists(armed):
                continue
            try:
                os.remove(armed)  # one-shot: disarm after firing
            except OSError:
                pass
            gate_val = _first_block_value(f, "gate") or "warn"
            key = cmd if cmd else "%s:%s" % (tool_name, file_path)
            return _fire_gate(sid, lesson_dir, key, gate_val, topic)

    return ""
