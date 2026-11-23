"""Closed state for lessons: `resolved_by` links a lesson block to its GitHub fix.
The daily cron marks the block resolved when the fix lands. Fails open without gh.
"""
import datetime
import os
import re
import shutil
import subprocess

_URL = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)/?$")
_SHORT = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
_JQ = '[.state, (.pull_request.merged_at // ""), (.state_reason // "")] | @tsv'
_TIMEOUT = 20


def parse_ref(value):
    """(owner, repo, number) from a GitHub issue/PR URL or `owner/repo#n`, else None."""
    value = (value or "").strip().strip("\"'")
    m = _URL.match(value) or _SHORT.match(value)
    if not m or any(part.strip(".") == "" for part in m.groups()[:2]):
        return None
    return m.groups()


def _blocks(lines):
    marks = [i for i, ln in enumerate(lines) if ln.rstrip("\n") == "---"]
    return [(marks[k] + 1, marks[k + 1]) for k in range(0, len(marks) - 1, 2)]


def _field(lines, start, end, key):
    prefix = key + ":"
    for ln in lines[start:end]:
        if ln.startswith(prefix):
            return ln[len(prefix):].strip()
    return ""


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    except OSError:
        return []


def resolved_provenances(path):
    """Provenances of the file's blocks that carry `status: resolved`."""
    lines = _read(path)
    return {_field(lines, s, e, "provenance") for s, e in _blocks(lines)
            if _field(lines, s, e, "status") == "resolved"}


def is_resolved(path, provenance):
    """True only when every block of this provenance is resolved, so one open block keeps its gate."""
    lines = _read(path)
    status = [_field(lines, s, e, "status") for s, e in _blocks(lines)
              if _field(lines, s, e, "provenance") == provenance]
    return bool(status) and all(x == "resolved" for x in status)


def _landed(ref, is_pr, runner):
    owner, repo, num = ref
    try:
        r = runner(["gh", "api", "repos/%s/%s/issues/%s" % (owner, repo, num), "--jq", _JQ],
                   capture_output=True, text=True, timeout=_TIMEOUT)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    state, merged, reason = ((r.stdout or "").strip("\n").split("\t") + ["", ""])[:3]
    if is_pr or merged.strip():
        return bool(merged.strip())
    return state.strip() == "closed" and reason.strip() == "completed"


def _mark(lines, start, end, today):
    block = [ln for ln in lines[start:end] if not ln.startswith("resolved_on:")]
    stamp = ["status: resolved\n", "resolved_on: %s\n" % today]
    idx = next((i for i, ln in enumerate(block) if ln.startswith("status:")), None)
    block = block + stamp if idx is None else block[:idx] + stamp + block[idx + 1:]
    return lines[:start] + block + lines[end:]


def _gh_ready(runner, which):
    if not which("gh"):
        return False
    try:
        return runner(["gh", "auth", "status"], capture_output=True, text=True,
                      timeout=_TIMEOUT).returncode == 0
    except Exception:
        return False


def sweep(lesson_dirs, runner=subprocess.run, which=shutil.which, today=None):
    """Mark linked lesson blocks resolved and return the changed topics."""
    if not _gh_ready(runner, which):
        return []
    today = today or datetime.date.today().isoformat()
    changed = []
    for d in lesson_dirs:
        try:
            names = sorted(n for n in os.listdir(d) if n.endswith(".md") and n != "INDEX.md")
        except OSError:
            continue
        for name in names:
            path = os.path.join(d, name)
            lines = _read(path)
            dirty = False
            for start, end in reversed(_blocks(lines)):
                raw = _field(lines, start, end, "resolved_by")
                ref = parse_ref(raw)
                if not ref or _field(lines, start, end, "status") == "resolved":
                    continue
                if _landed(ref, "/pull/" in raw, runner):
                    lines = _mark(lines, start, end, today)
                    dirty = True
            if not dirty:
                continue
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines)
                changed.append(name[:-3])
            except OSError:
                continue
    return changed
