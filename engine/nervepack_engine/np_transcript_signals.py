"""Deterministic friction signals from one Claude Code transcript and its subagents.

A deterministic transcript signal reader, run before capture distills struggles.
Beside np_turn_parse.py, the only other module that knows the transcript shape.
"""
# Adds human_interrupt and splits errors into permission_denied, hook_block, tool_error.
# Each error carries later_succeeded and attempts for the same tool.
# Subagent user messages are dispatch prompts, never human turns.
# stdlib only. Never raises. Excerpts can hold prompt text, and capture scrubs them.
import json
import os
import re

EXCERPT_CHARS = 200
_BLOCKED_CONTEXT = 80
_RENDER_MAX = 60

_SKILL_BODY = "Base directory for this skill"
_INTERRUPT = "[Request interrupted"
_INJECTED = ("<", _SKILL_BODY, "Another Claude session sent a message",
             "This session is being continued", 'Run the "')
_BLOCKED_EXEMPT = (_SKILL_BODY, "<system-reminder>")
# File and web content may merely mention the blocked patterns. Bash stays scanned.
_READERS = frozenset(("Read", "Grep", "Glob", "NotebookRead", "WebFetch"))
_BLOCKED = re.compile(r'"status"\s*:\s*"blocked"|start-blockers|this command was refused', re.I)
_PERMISSION = re.compile(
    r"permission to use \S+ (?:has been|was) denied|doesn't want to proceed"
    r"|tool use was rejected|denied by (?:the )?(?:auto[- ]mode|classifier|permission)", re.I)
_HOOK = re.compile(r"\bhook\b[^\n]{0,80}\b(?:error|blocked|block|denied)\b"
                   r"|blocked by (?:a |the )?\S*\s?hook", re.I)


def _records(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for number, raw in enumerate(fh, start=1):
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(data, dict):
                    yield number, data
    except OSError:
        return


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_text_of(b.get("text") or b.get("content") or "")
                        for b in content if isinstance(b, dict))
    return ""


def _user_text(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(str(b.get("text") or "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text").strip()
    return ""


def _clip(text, limit=EXCERPT_CHARS):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def error_kind(text):
    """Classify an is_error tool result."""
    if _PERMISSION.search(text):
        return "permission_denied"
    if _HOOK.search(text):
        return "hook_block"
    return "tool_error"


def _file_entries(path, is_subagent):
    name = os.path.basename(path)
    entries = []
    skill_runs = {}
    tool_names = {}
    results = []  # (entry or None, tool, is_error) in transcript order

    def add(category, line, excerpt, **extra):
        e = {"category": category, "file": name, "line": line, "excerpt": _clip(excerpt)}
        e.update(extra)
        entries.append(e)
        return e

    for line, rec in _records(path):
        kind = rec.get("type")
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if kind == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                tool = str(b.get("name") or "")
                if b.get("id"):
                    tool_names[str(b["id"])] = tool
                if tool == "Skill" and inp.get("skill"):
                    s = str(inp["skill"])
                    skill_runs[s] = skill_runs.get(s, 0) + 1
                    if skill_runs[s] > 1:
                        add("repeated_skill", line, "%s (run %d)" % (s, skill_runs[s]))
                elif tool.endswith("wrap_up") and inp.get("ask"):
                    add("question_to_human", line, str(inp["ask"]))
                elif tool == "AskUserQuestion":
                    qs = inp.get("questions") if isinstance(inp.get("questions"), list) else []
                    texts = [str(q["question"]) for q in qs if isinstance(q, dict) and q.get("question")]
                    if texts:
                        add("question_to_human", line, "; ".join(texts))
        elif kind == "user":
            text = _user_text(content)
            if text.startswith(_INTERRUPT):
                if not is_subagent:
                    add("human_interrupt", line, text)
            elif text and not text.startswith(_INJECTED):
                if not is_subagent:
                    add("human_turn", line, text)
            elif text and not text.startswith(_BLOCKED_EXEMPT):
                hit = _BLOCKED.search(text)
                if hit:
                    add("blocked_result", line, text[max(0, hit.start() - _BLOCKED_CONTEXT):])
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue
                tool = tool_names.get(str(b.get("tool_use_id")), "")
                result = _text_of(b.get("content"))
                if b.get("is_error"):
                    e = add(error_kind(result), line, result, tool=tool)
                    results.append((e, tool, True))
                    continue
                results.append((None, tool, False))
                if tool not in _READERS and _BLOCKED.search(result):
                    add("blocked_result", line, result)

    # Pair each error with the same tool's later outcome.
    for i, (entry, tool, is_error) in enumerate(results):
        if not is_error:
            continue
        attempts, succeeded = 1, False
        for _, later_tool, later_err in results[i + 1:]:
            if later_tool != tool:
                continue
            attempts += 1
            if not later_err:
                succeeded = True
                break
        entry["later_succeeded"] = succeeded
        entry["attempts"] = attempts
    return entries


def collect(transcript_path):
    """{"friction": [entry, ...]} for the transcript plus its subagent files."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return {"friction": []}
    friction = _file_entries(transcript_path, False)
    sub = os.path.join(os.path.splitext(transcript_path)[0], "subagents")
    try:
        names = sorted(n for n in os.listdir(sub) if n.endswith(".jsonl"))
    except OSError:
        names = []
    for n in names:
        friction += _file_entries(os.path.join(sub, n), True)
    return {"friction": friction}


def anchor(entry):
    return "%s:%s" % (entry.get("file"), entry.get("line"))


def anchors(signals):
    return {anchor(e) for e in signals.get("friction") or []}


def counts(signals):
    out = {}
    for e in signals.get("friction") or []:
        out[e["category"]] = out.get(e["category"], 0) + 1
    return out


def render(signals, limit=_RENDER_MAX):
    """One `file:line category: excerpt` line per entry for the capture prompt.
    Human turns are context, not friction, so they drop first when capped."""
    items = signals.get("friction") or []
    if not items:
        return ""
    keep = sorted(range(len(items)), key=lambda i: items[i]["category"] == "human_turn")[:limit]
    lines = []
    for e in (items[i] for i in sorted(keep)):
        extra = ""
        if "attempts" in e:
            extra = " [tool=%s attempts=%d later_succeeded=%s]" % (
                e.get("tool") or "?", e["attempts"], str(e["later_succeeded"]).lower())
        lines.append("%s %s%s: %s" % (anchor(e), e["category"], extra, e["excerpt"]))
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(json.dumps(collect(sys.argv[1] if len(sys.argv) > 1 else ""), indent=2, ensure_ascii=False))
