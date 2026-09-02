"""PreToolUse hook: the durable-text form gate.

Enforces the categorical rules of np-flow-concise-output (no em dash, no
semicolon, no contraction, no marketing adjective) on text that persists:
files, artifacts, Notion pages, Slack posts, work-item descriptions, and
commit messages. `form_gate.categorical` selects the mode: `ask`/`warn`/`off`
return "ask" or `allow`+context, exactly as before. Rate-based findings
(passive voice, sentence length) only ever add context in every mode.

`block` is the third deliberate blocking hook (ARCHITECTURE invariant 1): a
write carrying em_dash, semicolon, marketing_adjective, an over-length
sentence, or an over-length paragraph is denied outright, up to two retries
per (session, target). A third strike escalates to `ask` and emits a
struggles[] record to the episodic inbox so episodic-maintain can distill the
pattern. `contraction` never blocks -- it stays a rate-channel signal only.
The engine ships `categorical=warn`. `block` is opt-in.

Fails open everywhere, per ARCHITECTURE invariant 1: every counter-file and
inbox-write path is wrapped so a corrupt cache file or any exception falls
back to "" / allow, never a crash.

Channel A reads the linter's own violation counts and never reimplements its
regexes. The linter already excludes possessives from the contraction count.

`comment_ext` (empty by default -- inert until set) additionally scopes
source-file comments/docstrings into the same linter, via
`np_comment_extract.py`. In `block` mode only, a comment block longer than
`comment_block_max` lines injects a synthetic `long_comment_block` violation
that rides the same deny/retry/escalate machine as every other blocking rule.
See change-specs/feat-form-gate-comment-lint.md.
"""
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import np_capture
import np_comment_extract
import np_content
import np_dirs
import np_toggle

_PROSE_EXT_DEFAULT = ".md,.mdx,.markdown,.html,.txt,.rst,.adoc"

# Empty by default: the comment-lint feature is inert until a maintainer
# opts a source-file scope in via the toggle. See change-specs/
# feat-form-gate-comment-lint.md.
_COMMENT_EXT_DEFAULT = ""
_COMMENT_BLOCK_MAX_DEFAULT = 20

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

# The `block` mode's violation set. Narrower than _CATEGORICAL: contraction is
# common enough in ordinary writing that a hard block on it would fire
# constantly, so it stays counted toward the rate channel only, never blocking.
# The length keys MUST match np-ste-lint.py's own dict keys verbatim, including
# the `(>20w)`/`(>6s)` suffixes -- a bare `long_sentence` would `.get()` to 0
# against the real linter and silently never block.
_BLOCKING = ("em_dash", "semicolon", "marketing_adjective",
             "long_sentence(>20w)", "long_paragraph(>6s)", "long_comment_block")

_RULE_LABEL = {
    "em_dash": "em dash",
    "semicolon": "semicolon",
    "contraction": "contraction",
    "marketing_adjective": "marketing adjective",
    "long_sentence(>20w)": "long sentence (>20w)",
    "long_paragraph(>6s)": "long paragraph (>6s)",
    # Static fallback only -- run() always supplies the real threshold via
    # _blocking_hits' extra_labels, since the ceiling is a toggle param, not
    # a constant.
    "long_comment_block": "long comment block",
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


def _comment_ext():
    """Extensions the gate scans for comment prose, from the toggle.

    Empty by default -- unlike `_prose_ext`, an unset value means the
    comment-lint feature is INERT, not "fall back to a built-in list". A
    maintainer opts a scope in explicitly.
    """
    raw = np_toggle.param("form_gate.comment_ext", _COMMENT_EXT_DEFAULT) or _COMMENT_EXT_DEFAULT
    return tuple(e.strip().lower() for e in raw.split(",") if e.strip())


def _comment_block_max():
    try:
        return int(np_toggle.param("form_gate.comment_block_max",
                                    str(_COMMENT_BLOCK_MAX_DEFAULT))
                   or _COMMENT_BLOCK_MAX_DEFAULT)
    except (TypeError, ValueError):
        return _COMMENT_BLOCK_MAX_DEFAULT


def _is_comment_path(path):
    """A source file in the comment-lint scope. Prose files are excluded
    outright -- they already have their own path through `_prose_file`, and
    must never also pick up the comment-lint synthetic violation key."""
    if not path:
        return False
    exts = _comment_ext()
    return bool(exts) and path.lower().endswith(exts) and not _is_prose_path(path)


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


def _comment_source_text(tool_name, tool_input):
    """(path, content) for a Write/Edit, the same content each already lints
    as prose -- the text this write ADDS for Write, `new_string` for Edit."""
    path = tool_input.get("file_path")
    if tool_name == "Write":
        return path, _added_text(path, tool_input.get("content"))
    return path, tool_input.get("new_string")


def _comment_prose(path, content):
    """(comment_text, max_block_lines) for a comment-scoped path, via
    np_comment_extract. ("", 0) for anything it can't handle."""
    return np_comment_extract.extract_comments(content, os.path.splitext(path or "")[1])


def _comment_max_block(tool_name, tool_input):
    """max_block_lines for a comment-scoped Write/Edit, else 0 -- including
    for every prose file, so the length ceiling never fires on prose."""
    if tool_name not in ("Write", "Edit"):
        return 0
    path, content = _comment_source_text(tool_name, tool_input)
    if not _is_comment_path(path) or _is_exempt_path(path):
        return 0
    _, max_block = _comment_prose(path, content)
    return max_block


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
    if tool_name in ("Write", "Edit"):
        path, content = _comment_source_text(tool_name, tool_input)
        if _is_comment_path(path) and not _is_exempt_path(path):
            comment_text, _ = _comment_prose(path, content)
            if not comment_text:
                return (None, "")
            return (comment_text, os.path.basename(path))
        return _prose_file(path, content)
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


def _deny(reason):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
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


def _blocking_hits(violations, extra_labels=None):
    labels = _RULE_LABEL if not extra_labels else dict(_RULE_LABEL, **extra_labels)
    return [(labels[rule], int(violations.get(rule) or 0))
            for rule in _BLOCKING
            if int(violations.get(rule) or 0) > 0]


def _target(tool_name, tool_input, label):
    """The `block` retry counter's key subject: the file path for a file
    write, or the MCP/tool label for anything else (an MCP send, a commit
    message, an artifact comment reply)."""
    if tool_name in ("Write", "Edit"):
        path = tool_input.get("file_path")
        if path:
            return path
    if tool_name == "Artifact" and tool_input.get("action") != "reply":
        path = tool_input.get("file_path")
        if path:
            return path
    return label


def _retry_dir():
    return os.environ.get("FORM_GATE_RETRY_DIR") or np_dirs.cache_path("form-gate-retry")


def _retry_path(sid, target):
    key = hashlib.sha256(("%s\x1f%s" % (sid, target)).encode("utf-8", "replace")).hexdigest()
    return os.path.join(_retry_dir(), key + ".count")


def _read_retry(sid, target):
    """Current retry count for this (session, target). Fail-open 0: a corrupt
    or missing counter file is treated as a fresh start, never as a crash."""
    try:
        with open(_retry_path(sid, target), encoding="utf-8") as fh:
            return int((fh.read() or "0").strip())
    except (OSError, ValueError):
        return 0


def _write_retry(sid, target, count):
    """Persist the retry count. Returns True on success, False if the counter
    could not be written. The caller MUST NOT hard-deny on a False return: a
    counter that never persists would read 0 every time, so the budget would
    never fill and the user would be trapped in permanent denies with no
    escalation. A failed write escalates instead."""
    try:
        os.makedirs(_retry_dir(), exist_ok=True)
        with open(_retry_path(sid, target), "w", encoding="utf-8") as fh:
            fh.write(str(count))
        return True
    except OSError:
        return False


def _clear_retry(sid, target):
    try:
        os.remove(_retry_path(sid, target))
    except OSError:
        pass


def _emit_escalation_struggle(sid, payload, label, detail):
    """Append a struggles[] record to the episodic inbox so episodic-maintain
    distills this pattern into memory/lessons/. Every part of this fails open:
    an error here must never change the gate's decision, so the whole thing is
    one try/except with no re-raise."""
    try:
        cwd = payload.get("cwd") or os.getcwd()
        project = os.path.basename(cwd.rstrip(os.sep) or "unknown") or "unknown"
        symptom = ("form gate escalated to ask after 2 blocks on %s: %s"
                   % (label, detail))
        record = {
            "session_id": sid,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "project": project,
            "cwd": cwd,
            "mode": "form-gate-escalation",
            "headline": "form gate escalated to ask on %s" % label,
            "body": "%s. Rewrite could not satisfy the linter." % symptom,
            "candidate_topics": ["form-gate"],
            "keywords": ["form-gate", "escalation", label],
            "struggles": [{
                "symptom": symptom,
                "cause": "rewrite could not satisfy the linter after 2 attempts",
                "fix": "tune np-ste-lint.py or the np-flow-concise-output rule calibration",
                "tool_match": "",
                "topic_triggers": ["form-gate", "np-ste-lint", "np-flow-concise-output"],
                "destructive": False,
            }],
        }
        np_capture.append_note(record)
    except Exception as exc:
        # Fail-open: a struggle-capture loss must never change the decision. Log
        # a signal so an operator can see the escalation pattern went unrecorded.
        try:
            np_toggle.signal(sid, "form-gate-struggle-emit-failed :: %s" % exc)
        except Exception:
            pass


def _run_block(sid, target, label, violations, payload, extra_labels=None):
    hits = _blocking_hits(violations, extra_labels)
    if not hits:
        _clear_retry(sid, target)
        return ""

    detail = ", ".join("%s x%d" % (name, count) for name, count in hits)
    count = _read_retry(sid, target)
    # Deny only while the budget has room AND the incremented count actually
    # persisted. A failed write falls through to escalation, never to another
    # deny -- otherwise an unwritable cache dir traps the user in permanent
    # denies with no way out.
    if count < 2:
        if _write_retry(sid, target, count + 1):
            message = ("%s breaks an absolute rule of np-flow-concise-output: %s. "
                       "Rewrite without them and retry." % (label, detail))
            return _deny(message)
        # Counter did not persist. Escalate rather than loop, and signal so this
        # is distinguishable from a genuine third strike when debugging.
        np_toggle.signal(sid, "form-gate-cache-write-failed :: %s" % label)

    _clear_retry(sid, target)
    message = ("%s still breaks an absolute rule of np-flow-concise-output: %s. "
               "The linting rules may need tuning -- see np-ste-lint.py and "
               "np-flow-concise-output." % (label, detail))
    np_toggle.signal(sid, "form-gate-escalation :: %s :: %s" % (label, detail))
    _emit_escalation_struggle(sid, payload, label, detail)
    return _ask(message)


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

    categorical = _mode("form_gate.categorical", "ask", ("ask", "warn", "off", "block"))

    if categorical == "block":
        extra_labels = None
        comment_block_max = _comment_block_max()
        max_block = _comment_max_block(tool_name, tool_input)
        if max_block > comment_block_max:
            violations = dict(violations)
            violations["long_comment_block"] = 1
            extra_labels = {"long_comment_block":
                            "long comment block (>%d lines)" % comment_block_max}
        target = _target(tool_name, tool_input, label)
        return _run_block(sid, target, label, violations, payload, extra_labels)

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
