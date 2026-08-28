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

_PROSE_EXT_DEFAULT = ".md,.mdx,.markdown,.html,.txt,.rst,.adoc"

# Text keys worth linting on a tool whose payload shape is not worth hardcoding.
# MCP schemas drift, and a gate that silently stops matching after a server
# renames a field is worse than one that scans a short candidate list.
# Both payload walkers are recursive over attacker-shaped JSON. Real payloads
# nest three or four levels; a pathological one would blow the stack and take
# the tool call with it. A hook that crashes a session gets uninstalled.
_MAX_WALK_DEPTH = 24

_TEXT_KEYS = ("content", "text", "body", "comment", "markdown", "message",
              "description")

# suffix -> label. The four originals plus the surfaces the skill names and the
# gate never saw: review-thread replies, work-item comments, wiki upserts,
# Notion page creation, Slack drafts and canvases, mail.
_GATED_MCP = {
    "slack_send_message": "Slack message",
    "slack_send_message_draft": "Slack draft",
    "slack_schedule_message": "Slack message",
    "slack_create_canvas": "Slack canvas",
    "slack_update_canvas": "Slack canvas",
    "repo_pull_request_write": "PR description",
    "repo_pull_request_thread_write": "PR thread reply",
    "wit_work_item_write": "work-item description",
    "wit_work_item_comment_write": "work-item comment",
    "wiki_upsert_page": "wiki page",
    "notion-update-page": "Notion page",
    "notion-create-pages": "Notion page",
    "notion-create-comment": "Notion comment",
    "create_draft": "mail draft",
    "send_message": "message",
    "reply": "mail reply",
    "forward": "mail forward",
}

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


def _prose_ext():
    """Extensions the gate treats as prose, from the toggle.

    A param rather than a constant so one person can widen it without the
    engine imposing that choice on a forker. Source files stay out by default:
    the linter strips code, and scoring what is left of a module is noise.
    """
    raw = np_toggle.param("form_gate.prose_ext", _PROSE_EXT_DEFAULT) or _PROSE_EXT_DEFAULT
    exts = tuple(e.strip().lower() for e in raw.split(",") if e.strip())
    return exts or tuple(_PROSE_EXT_DEFAULT.split(","))


def _is_prose_path(path):
    return bool(path) and path.lower().endswith(_prose_ext())


def _split_globs(raw):
    """Split the exempt-glob list without shredding a Windows drive letter.

    Both platform separators are accepted, so a config synced between machines
    keeps working. A colon directly after a single letter that opens a fragment
    is a drive, not a separator: splitting "C:\\Users\\pat" on a bare colon
    yields "C" and "\\Users\\pat", and neither fragment matches anything. That
    fails toward "nothing is exempt", which is the direction that fires the
    gate on voiced prose.
    """
    merged = []
    for part in re.split(r"[;:]", raw or ""):
        if (merged and len(merged[-1]) == 1 and merged[-1].isalpha()
                and part[:1] in ("\\", "/")):
            merged[-1] = "%s:%s" % (merged[-1], part)
        else:
            merged.append(part)
    return [p.strip() for p in merged if p.strip()]


def _exempt_globs():
    """Globs from the toggle, with ~ expanded and separators normalized.

    np_toggle does NOT expand ~. An unexpanded glob matches nothing, which
    fails open into "nothing is exempt" -- the direction that fires the gate
    on voiced prose. Expand here or the exemption is silently dead.

    normpath puts the glob on the same separator as the target, which
    _is_exempt_path normalizes through abspath. It leaves * and ** untouched.
    """
    raw = np_toggle.param("form_gate.exempt_globs", "") or ""
    return [os.path.normpath(os.path.expanduser(g)) for g in _split_globs(raw)]


def _is_exempt_path(path):
    if not path:
        return False
    if _EXEMPT.search(path):
        return True
    target = os.path.abspath(os.path.expanduser(path))
    for glob in _exempt_globs():
        if fnmatch.fnmatch(target, glob):
            return True
        # A glob naming a directory with no wildcard still covers what sits
        # under it, which fnmatch on its own would not match.
        base = glob.rstrip("*").rstrip(os.path.sep)
        if base and target.startswith(base + os.path.sep):
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


def _added_text(path, content):
    """Only what this write ADDS to the file already on disk.

    Write replaces a whole file, so linting the payload scores prose the author
    may never have touched. Edit already lints only `new_string`. Matching that
    here is what removes the 579 pre-existing violations as a reason to keep
    `categorical` at warn: a rewrite of an old doc is judged on what it
    introduces, not on what it inherited.

    A line-set comparison, not a real diff. A moved line reads as unchanged,
    which is correct (it was already the author's text), and a reworded line
    reads as added, which is also correct. Any read error means the file is new
    or unreadable, so everything in it counts as new.
    """
    if not path:
        # A Write with no file_path never reaches _prose_file's own guard,
        # because this runs first. open(None) raises TypeError, not OSError,
        # so the except below would not catch it and the hook would die.
        return content
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            before = set(fh.read().splitlines())
    except OSError:
        return content
    return "\n".join(line for line in (content or "").splitlines()
                      if line.strip() and line not in before)


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
        path = tool_input.get("file_path")
        return _prose_file(path, _added_text(path, tool_input.get("content")))
    if tool_name == "Edit":
        return _prose_file(tool_input.get("file_path"),
                           tool_input.get("new_string"))
    if tool_name == "SendUserFile":
        # The files themselves were gated when they were written. The caption
        # is new prose that nothing else sees.
        return (tool_input.get("caption") or None, "file caption")
    if tool_name == "Artifact":
        if tool_input.get("action") == "reply":
            return (tool_input.get("text") or None, "artifact comment reply")
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
    label = _GATED_MCP.get(suffix)
    if not label:
        return (None, "")
    # Two payloads need structure walked rather than keys read.
    if suffix.startswith("notion-"):
        return (_notion_prose(tool_input), label)
    if suffix == "wit_work_item_write":
        return (_work_item_prose(tool_input), label)
    if suffix == "repo_pull_request_write":
        return (tool_input.get("description") or None, label)
    return (_keyed_prose(tool_input), label)


def _keyed_prose(tool_input):
    """Concatenate the string values under any known text key, at any depth.

    Depth matters: a Slack canvas and a wiki upsert both nest their body one or
    two levels down, and a top-level-only read would gate neither.
    """
    chunks = []

    def walk(node, keyed, depth):
        if depth > _MAX_WALK_DEPTH:
            return
        if isinstance(node, str):
            if keyed:
                chunks.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item, keyed, depth + 1)
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, keyed or key in _TEXT_KEYS, depth + 1)

    walk(tool_input, False, 0)
    joined = "\n".join(c for c in chunks if c.strip())
    return joined or None


def _notion_prose(tool_input):
    """Concatenate the prose bodies of a notion-update-page command payload.

    The payload shape varies by command, so this walks it defensively and
    keeps only string values under content-ish keys. A table cell holding a
    bare fact is not prose and is not worth gating.
    """
    chunks = []

    def walk(node, depth=0):
        if depth > _MAX_WALK_DEPTH:
            return
        if isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in ("content", "new_str", "text", "body"):
                    walk(value, depth + 1)

    walk(tool_input.get("command") or tool_input.get("pages")
         or tool_input.get("content") or tool_input)
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


def _mode(param, default, allowed):
    value = (np_toggle.param(param, default) or default).strip().lower()
    return value if value in allowed else default


def _lint(text, timeout_s):
    """Run the overlay linter over text. Return its report dict, or None."""
    script = _lint_path()
    if not script:
        return None
    try:
        proc = subprocess.run(
            [sys.executable, script], input=text, capture_output=True,
            text=True, timeout=timeout_s, check=False)
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return data if isinstance(data, dict) else None


def _ask(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": reason,
    }}, separators=(",", ":"))


def _allow_with_context(context):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "additionalContext": context,
    }}, separators=(",", ":"))


def _categorical_hits(violations):
    return [(_RULE_LABEL[rule], int(violations.get(rule) or 0))
            for rule in _CATEGORICAL
            if int(violations.get(rule) or 0) > 0]


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

    try:
        timeout_s = float(np_toggle.param("form_gate.timeout_s", "5") or 5)
    except (TypeError, ValueError):
        timeout_s = 5.0

    report = _lint(_strip_quoted(text), timeout_s)
    if not report:
        return ""

    violations = report.get("violations") or {}
    sid = payload.get("session_id") or "unknown"

    categorical = _mode("form_gate.categorical", "ask", ("ask", "warn", "off"))
    hits = _categorical_hits(violations) if categorical != "off" else []

    if hits:
        detail = ", ".join("%s x%d" % (name, count) for name, count in hits)
        message = ("%s breaks an absolute rule of np-flow-concise-output: %s. "
                   "These are zero-tolerance, not rate-based. Rewrite without "
                   "them, then retry." % (label, detail))
        np_toggle.signal(sid, "form-gate %s categorical :: %s"
                         % (categorical, ", ".join(n for n, _ in hits)))
        return _ask(message) if categorical == "ask" else _allow_with_context(message)

    if _mode("form_gate.rate", "warn", ("warn", "off")) == "off":
        return ""
    try:
        threshold = float(np_toggle.param("form_gate.rate_threshold", "2.5") or 2.5)
    except (TypeError, ValueError):
        threshold = 2.5
    score = report.get("total_per100w")
    if score is None or float(score) <= threshold:
        return ""

    top = sorted(((k, int(v)) for k, v in violations.items() if v),
                 key=lambda kv: -kv[1])[:3]
    detail = ", ".join("%s=%d" % (k, v) for k, v in top) or "see np-ste-lint.py"
    np_toggle.signal(sid, "form-gate rate :: %.1f" % float(score))
    return _allow_with_context(
        "%s scores %.1f violations per 100 words against a threshold of %.1f "
        "(%s). See np-flow-concise-output." % (label, float(score), threshold, detail))
