"""Extract the CURRENT TURN from a Claude Code transcript JSONL.

Pure by design: one file read, no toggles, no hook JSON, no subprocess. This is
the single place that knows Claude Code's transcript shape, so a format change
has exactly one file to fix (turn_gate.py stays untouched).

Turn boundary: the last record with type=="user" AND promptSource=="typed".
Tool results ALSO arrive as type:"user" records, so the type alone is not
enough -- the same allowlist np-transcript-extract.py:last_user_text documents.
"""
import json
import os
import re

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
_VIEWER_TOOL = re.compile(r"mcp__.*(screenshot|browser|playwright|simulator)", re.I)
_OPEN_CMD = re.compile(r"(?:^|[|;&\s])(open|xdg-open)\s", re.I)
_EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")

_FENCE = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.S)
_DIFF_MARKER = re.compile(r"^(?:@@ .*@@|--- |\+\+\+ )", re.M)


def has_diff_shape(text):
    """True if text contains a fenced code block that looks like a rendered
    unified diff: a ``diff``-tagged fence, or one whose body has a unified-diff
    line marker (a hunk header, or a --- /+++ file-header pair). Covers a
    hand-typed diff pasted straight into the response, which np-md-diff.py
    never touches and turn.delivery never records."""
    if not text:
        return False
    for m in _FENCE.finditer(text):
        lang = (m.group(1) or "").strip().lower()
        if lang == "diff" or _DIFF_MARKER.search(m.group(2)):
            return True
    return False


class Turn(object):
    """One turn's observable facts. Always fully populated, never None."""

    def __init__(self):
        self.edits = []       # file paths written or edited
        self.created = []     # subset of edits written via a tool that implies
                               # no pre-existing base (Write) -- Edit always
                               # requires a prior Read, so it never lands here
        self.delivery = []    # labels describing how something was shown
        self.final_text = ""  # the closing assistant text block


def _records(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue  # tolerate a stray non-JSON line


def _blocks(rec):
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _is_typed_user(rec):
    return rec.get("type") == "user" and rec.get("promptSource") == "typed"


def _scan(rec, turn):
    for blk in _blocks(rec):
        kind = blk.get("type")

        if kind == "image":
            turn.delivery.append("image block")

        elif kind == "tool_result":
            inner = blk.get("content")
            if isinstance(inner, list) and any(
                isinstance(x, dict) and x.get("type") == "image" for x in inner
            ):
                turn.delivery.append("image returned by a tool")

        elif kind == "text" and rec.get("type") == "assistant":
            text = blk.get("text") or ""
            if text.strip():
                turn.final_text = text

        elif kind == "tool_use":
            name = blk.get("name") or ""
            inp = blk.get("input") or {}
            path = str(inp.get("file_path") or "")

            if name in _EDIT_TOOLS and path:
                turn.edits.append(path)
                if name == "Write":
                    turn.created.append(path)
            if name == "Read" and path.lower().endswith(_IMAGE_EXT):
                turn.delivery.append("read an image")
            if name == "SendUserFile":
                turn.delivery.append("sent a file to the user")
            if _VIEWER_TOOL.search(name):
                turn.delivery.append("browser or screenshot tool")
            if name == "Bash" and _OPEN_CMD.search(str(inp.get("command") or "") + " "):
                turn.delivery.append("opened in a browser")
            if name == "Bash" and "np-md-diff" in str(inp.get("command") or ""):
                turn.delivery.append("ran np-md-diff")


def parse(path):
    """Return the Turn for the transcript's current turn. Never raises."""
    turn = Turn()
    if not path or not os.path.isfile(path):
        return turn
    try:
        records = list(_records(path))
    except OSError:
        return turn

    start = 0
    for i in range(len(records) - 1, -1, -1):
        if _is_typed_user(records[i]):
            start = i
            break

    for rec in records[start:]:
        _scan(rec, turn)
    return turn
