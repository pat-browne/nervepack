"""PreToolUse hook: the durable-text form gate.

Enforces the categorical rules of np-flow-concise-output (no em dash, no
semicolon, no contraction, no marketing adjective) on text that persists:
files, artifacts, Notion pages, Slack posts, work-item descriptions, and
commit messages. Categorical hits return "ask". Rate-based findings (passive
voice, sentence length) only ever add context.

Fails open everywhere, per ARCHITECTURE invariant 1. "ask" is a permission
prompt rather than a block, so this hook needs no amendment to that invariant;
it follows the precedent lesson_guard already set.

Channel A reads the linter's own violation counts and never reimplements its
regexes. The linter already excludes possessives from the contraction count.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

import np_content
import np_toggle

_PROSE_EXT = (".md", ".mdx", ".html", ".txt")

# Mirrors turn_gate._EXEMPT so the two prose gates agree on what is not prose.
_EXEMPT = re.compile(r"(^|[/\\])(tests?|fixtures?|__snapshots__|node_modules"
                     r"|dist|build)([/\\]|$)|\.min\.", re.I)

_CATEGORICAL = ("em_dash", "semicolon", "contraction", "marketing_adjective")

_RULE_LABEL = {
    "em_dash": "em dash",
    "semicolon": "semicolon",
    "contraction": "contraction",
    "marketing_adjective": "marketing adjective",
}


def _is_prose_path(path):
    return bool(path) and path.lower().endswith(_PROSE_EXT)


def _exempt_globs():
    """Colon-separated globs from the toggle, with ~ expanded.

    np_toggle does NOT expand ~. An unexpanded glob matches nothing, which
    fails open into "nothing is exempt" -- the direction that fires the gate
    on voiced prose. Expand here or the exemption is silently dead.
    """
    raw = np_toggle.param("form_gate.exempt_globs", "") or ""
    return [os.path.expanduser(g) for g in raw.split(":") if g.strip()]


def _is_exempt_path(path):
    if not path:
        return False
    if _EXEMPT.search(path):
        return True
    target = os.path.abspath(os.path.expanduser(path))
    for glob in _exempt_globs():
        if fnmatch.fnmatch(target, glob):
            return True
        # fnmatch does not treat ** as crossing separators; a prefix test does.
        base = glob.rstrip("*").rstrip(os.sep)
        if base and target.startswith(base + os.sep):
            return True
    return False


def _lint_path():
    """Absolute path to the overlay's STE linter, or None.

    The engine ships no linter. With no overlay configured, the gate never
    fires. Same contract as turn_gate._lint_path.
    """
    try:
        root = np_content.content_dir()
    except Exception:
        return None
    if not root:
        return None
    path = os.path.join(root, "engine", "setup", "np-ste-lint.py")
    return path if os.path.isfile(path) else None


_GIT_COMMIT = re.compile(r"\bgit\s+commit\b")
_GIT_MSG = re.compile(r"-m\s+(\"([^\"]*)\"|'([^']*)')")


def _strip_quoted(text):
    """Remove somebody else's words and non-prose scaffolding.

    Mirrors what np-kb-voice's own detector strips: markdown headings,
    embedded HTML, and blockquoted material. A section header or a quoted
    line is not the author's prose, so it must not score against them.
    """
    text = re.sub(r"^[ \t]{0,3}>.*$", "", text, flags=re.M)
    text = re.sub(r"^[ \t]{0,3}#{1,6}[ \t].*$", "", text, flags=re.M)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def _prose_file(path, content):
    if not _is_prose_path(path) or _is_exempt_path(path):
        return (None, "")
    return (content or None, os.path.basename(path))


def _git_commit_message(command):
    if not command or not _GIT_COMMIT.search(command):
        return None
    match = _GIT_MSG.search(command)
    if not match:
        return None
    return match.group(2) if match.group(2) is not None else match.group(3)


def _mcp_suffix(tool_name):
    """Trailing segment of an mcp__<server>__<tool> name, else ""."""
    return tool_name.rsplit("__", 1)[-1] if tool_name.startswith("mcp__") else ""


def _extract(tool_name, tool_input):
    """Return (text, label) for a gated tool, or (None, "") to allow."""
    if tool_name == "Write":
        return _prose_file(tool_input.get("file_path"),
                           tool_input.get("content"))
    if tool_name == "Edit":
        return _prose_file(tool_input.get("file_path"),
                           tool_input.get("new_string"))
    if tool_name == "Artifact":
        path = tool_input.get("file_path")
        if not _is_prose_path(path) or _is_exempt_path(path):
            return (None, "")
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return (fh.read() or None, os.path.basename(path))
        except OSError:
            return (None, "")
    if tool_name == "Bash":
        message = _git_commit_message(tool_input.get("command"))
        return (message, "commit message") if message else (None, "")

    suffix = _mcp_suffix(tool_name)
    if suffix == "slack_send_message":
        return (tool_input.get("text") or None, "Slack message")
    if suffix == "repo_pull_request_write":
        return (tool_input.get("description") or None, "PR description")
    if suffix == "notion-update-page":
        return (_notion_prose(tool_input), "Notion page")
    if suffix == "wit_work_item_write":
        return (_work_item_prose(tool_input), "work-item description")
    return (None, "")


def _notion_prose(tool_input):
    """Concatenate the prose bodies of a notion-update-page command payload.

    The payload shape varies by command, so this walks it defensively and
    keeps only string values under content-ish keys. A table cell holding a
    bare fact is not prose and is not worth gating.
    """
    chunks = []

    def walk(node):
        if isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in ("content", "new_str", "text", "body"):
                    walk(value)

    walk(tool_input.get("command") or tool_input.get("content") or tool_input)
    joined = "\n".join(c for c in chunks if c.strip())
    return joined or None


def _work_item_prose(tool_input):
    fields = tool_input.get("fields")
    if isinstance(fields, dict):
        for key, value in fields.items():
            if "description" in key.lower() and isinstance(value, str):
                return value or None
    if isinstance(fields, list):
        for entry in fields:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("path") or "")
            if "description" in name.lower():
                value = entry.get("value")
                if isinstance(value, str):
                    return value or None
    value = tool_input.get("description")
    return value or None


def run(payload_text):
    if not np_toggle.enabled("form_gate"):
        return ""
    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""

    try:
        text, label = _extract(tool_name, tool_input)
    except Exception:
        return ""
    if not text or not text.strip():
        return ""

    return ""
