"""Shared helpers for reading Claude Code session transcripts (the
~/.claude/projects/*/*.jsonl files) that several hooks consume.

extract_cwd() was copied verbatim into backcapture_sweep, resume_sessionstart, and
resume_write (the last even recompiled the regex on every call). Each hook's
per-purpose discovery -- which sessions to pick, the age/skip rules -- stays in the
hook; only this identical line-scan for the session cwd lives here. (#176)
"""
import json
import re

_CWD_RE = re.compile(r'"cwd":"([^"]*)"')


def extract_cwd(path):
    """The session's cwd from the first transcript line that records one (the JSON
    `"cwd":"..."` field, unescaped), or None if the file is unreadable / has none."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _CWD_RE.search(line)
                if m:
                    try:
                        return json.loads('"' + m.group(1) + '"')
                    except ValueError:
                        return m.group(1)
    except OSError:
        pass
    return None
