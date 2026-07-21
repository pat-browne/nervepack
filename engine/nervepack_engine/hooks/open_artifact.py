"""PostToolUse hook (matcher: Write): when a spec or plan doc is created under
docs/superpowers/{specs,plans}/*.md, open it with the OS default handler so a
human's attention actually lands on it instead of a chat line saying "written
to ..." (design: specs/2026-07-21-open-artifact-on-write-design.md). Reuses
np_dashboard.resolve_opener() -- `open`/`xdg-open` work on any local path, not
just dashboard URLs, so no new opener-resolution logic is needed. opener_fn is
injectable for tests (defaults to a real subprocess call).
"""
import json
import os
import re
import subprocess

import np_dashboard
import np_toggle

_ARTIFACT_RE = re.compile(r"[/\\]docs[/\\]superpowers[/\\](?:specs|plans)[/\\][^/\\]+\.md$")


def _default_opener(path):
    opener = np_dashboard.resolve_opener()
    if not opener:
        return
    try:
        subprocess.run([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass


def run(payload_text, opener_fn=None):
    if not np_toggle.enabled("focus"):
        return ""

    try:
        payload = json.loads(payload_text or "{}")
    except ValueError:
        return ""

    if payload.get("tool_name") != "Write":
        return ""

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        return ""

    cwd = payload.get("cwd") or ""
    abs_path = file_path if os.path.isabs(file_path) else os.path.normpath(os.path.join(cwd, file_path))

    # Match against the resolved absolute path, not the raw (possibly relative)
    # file_path -- a relative path with no parent segment (e.g. "docs/superpowers/
    # specs/x.md") has no leading separator before "docs" and would miss the regex.
    if not _ARTIFACT_RE.search(abs_path) or not os.path.isfile(abs_path):
        return ""

    # Gate on a resolvable opener BEFORE calling opener_fn -- this must hold even
    # when opener_fn is test-injected, so "no opener available" fails open
    # regardless of which opener callable is in play (mirrors open_dashboard.py).
    if not np_dashboard.resolve_opener():
        return ""

    try:
        (opener_fn or _default_opener)(abs_path)
    except Exception:
        pass

    return ""
