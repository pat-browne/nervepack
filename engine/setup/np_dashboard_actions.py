#!/usr/bin/env python3
"""Data helpers behind the dashboard's compact-proposal and graduation panels.

Shared by dashboard/build.py (render) and np-dashboard-server.py (actions).
Stdlib only. Reads fail open.

Compact proposals live at <content>/compact-proposals/<YYYY-MM-DD>.md.
agents/np-flow-weekly-compact.md writes them.

Each `### a vs b` heading opens one proposal. It runs to the next heading.

REJECTED.md in the same dir holds one-line rejection notes.
The compact agent reads it so it does not re-propose a rejected pair.

Graduation dismissals sit next to graduation-candidates.json.
The file is graduation-dismissed.json, a JSON list of "<kind>:<name>" keys.
"""
import json
import os
import re
import time

PROPOSAL_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_HEAD_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")
_REC_RE = re.compile(r"recommendation\s*:?\s*\**\s*:?\s*(.+)", re.I)


def _sections(lines):
    """[(title, start, end)] for each `### ` heading. End is exclusive."""
    heads = []
    for i, line in enumerate(lines):
        m = _HEAD_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))

    out = []
    for n, (i, level, title) in enumerate(heads):
        if level != 3:
            continue
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out.append((title, i, end))
    return out


def _recommendation(body_lines):
    for line in body_lines:
        m = _REC_RE.search(line)
        if m:
            return m.group(1).strip().strip("*").strip().rstrip(".").strip()[:240]
    return ""


def parse_proposals(path):
    """[{title, recommendation, keep_separate}] for one proposal file."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []

    out = []
    for title, start, end in _sections(lines):
        rec = _recommendation(lines[start + 1:end])
        out.append({"title": title, "recommendation": rec,
                    "keep_separate": "keep separate" in rec.lower()})
    return out


def load_proposals(pdir):
    """[{file, date, proposals}] newest first. Files with no entries are skipped."""
    try:
        names = sorted((n for n in os.listdir(pdir) if PROPOSAL_FILE_RE.match(n)), reverse=True)
    except OSError:
        return []

    out = []
    for n in names:
        props = parse_proposals(os.path.join(pdir, n))
        if props:
            out.append({"file": n, "date": n[:-3], "proposals": props})
    return out


def find_proposal(pdir, fname, title):
    """The proposal dict, or None. Any name outside PROPOSAL_FILE_RE is refused."""
    if not PROPOSAL_FILE_RE.match(fname or ""):
        return None
    for p in parse_proposals(os.path.join(pdir, fname)):
        if p["title"] == title:
            return p
    return None


def reject_proposal(pdir, fname, title, today=None):
    """Note the rejection in REJECTED.md and drop the entry from its file.

    The file is deleted once no `###` entry remains.
    Returns True when the entry existed.
    """
    if not find_proposal(pdir, fname, title):
        return False

    path = os.path.join(pdir, fname)
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    sec = next((s for s in _sections(lines) if s[0] == title), None)
    if sec is None:  # entry vanished since find_proposal()
        return False
    rest = lines[:sec[1]] + lines[sec[2]:]
    rec = _recommendation(lines[sec[1] + 1:sec[2]])

    day = today or time.strftime("%Y-%m-%d")
    note = "- %s | %s | %s | rejected from dashboard%s\n" % (
        day, fname, title, (" (" + rec + ")") if rec else "")
    # Drop the entry first (atomic replace), then record it, so a failure
    # never leaves a recorded rejection whose entry still shows.
    if _sections(rest):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rest).rstrip("\n") + "\n")
        os.replace(tmp, path)
    else:
        os.remove(path)
    with open(os.path.join(pdir, "REJECTED.md"), "a", encoding="utf-8") as fh:
        fh.write(note)
    return True


def dismiss_key(kind, name):
    return "%s:%s" % (kind or "", name or "")


def load_dismissed(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [k for k in data if isinstance(k, str)] if isinstance(data, list) else []


def dismiss(path, kind, name):
    keys = load_dismissed(path)
    key = dismiss_key(kind, name)
    if key in keys:
        return keys

    keys.append(key)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(keys, fh, indent=1)
    os.replace(tmp, path)
    return keys


def filter_candidates(grad, dismissed):
    """Graduation payload with dismissed candidates removed."""
    drop = set(dismissed)
    cands = [c for c in grad.get("candidates", [])
             if isinstance(c, dict) and dismiss_key(c.get("kind"), c.get("name")) not in drop]
    return dict(grad, candidates=cands)


def find_candidate(path, kind, name):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None

    for c in (data.get("candidates") or []) if isinstance(data, dict) else []:
        if isinstance(c, dict) and c.get("kind") == kind and c.get("name") == name:
            return c
    return None
