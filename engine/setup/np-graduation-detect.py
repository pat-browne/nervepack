#!/usr/bin/env python3
"""Deterministic graduation detector for the daily skill-maintenance routine.

Strategies and playbooks are auto-distilled, low-authority, human-review-WAIVED
layers. They are meant to be a *staging pool* for skills, not a permanent home:
once an entry has proven itself (recurs often -> high `seen`) or has outgrown what
a skill body is even allowed to be (bytes over the skill soft budget), it should
GRADUATE into a human-reviewed `skills/np-*` skill (via np-core-contribute) and be
marked `status: graduated`. Without a trigger, entries accrete forever instead of
graduating -- which is exactly how a strategy like `security-review` grew past the
skill budget. This detector flags the candidates; it never acts (graduation crosses
the human-review gate that skills require).

Scans <strategies_dir> (kind=strategy) and optional <playbooks_dir> (kind=playbook)
for *.md entries and flags any not already graduated/promoted/archived that exceed
either threshold. No LLM. Thresholds via env (the cron resolves them from toggle
params; tests set them directly), with built-in defaults:

    GRADUATE_SEEN  (default 10)  recurrence count that proves the pattern
    GRADUATE_KB    (default 6)   bytes over this (= skill soft budget) is overdue

Usage: np-graduation-detect.py <strategies_dir> [playbooks_dir]
Emits one JSON object to stdout. Fail-open: on error, an empty report.
"""
import json
import os
import sys

SKIP_NAMES = {"INDEX.md", "README.md"}
DONE_STATUS = {"graduated", "promoted", "archived"}


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _frontmatter_field(text, field):
    """Value of frontmatter `<field>:` (first block); '' if none."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    for line in text[3:end].splitlines():
        if line.startswith(field + ":"):
            return line[len(field) + 1:].strip()
    return ""


def _scan_dir(d, kind, seen_min, byte_min):
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".md") or name in SKIP_NAMES or name.startswith("."):
            continue
        path = os.path.join(d, name)
        if not os.path.isfile(path):
            continue
        try:
            nbytes = os.path.getsize(path)
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        if _frontmatter_field(text, "status").lower() in DONE_STATUS:
            continue
        try:
            seen = int(_frontmatter_field(text, "seen") or 0)
        except ValueError:
            seen = 0
        reasons = []
        if seen >= seen_min:
            reasons.append("seen")
        if nbytes > byte_min:
            reasons.append("bytes")
        if reasons:
            out.append({"kind": kind, "name": name[:-3], "seen": seen,
                        "bytes": nbytes, "reasons": reasons})
    return out


def scan(strategies_dir, playbooks_dir):
    seen_min = _int_env("GRADUATE_SEEN", 10)
    kb = _int_env("GRADUATE_KB", 6)
    byte_min = kb * 1024
    cands = _scan_dir(strategies_dir, "strategy", seen_min, byte_min)
    if playbooks_dir:
        cands += _scan_dir(playbooks_dir, "playbook", seen_min, byte_min)
    cands.sort(key=lambda c: (-c["seen"], c["name"]))
    return {"candidates": cands,
            "thresholds": {"graduate_seen": seen_min, "graduate_kb": kb}}


def main(argv):
    strategies_dir = argv[1] if len(argv) > 1 else ""
    playbooks_dir = argv[2] if len(argv) > 2 else ""
    print(json.dumps(scan(strategies_dir, playbooks_dir), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:
        print(json.dumps({"candidates": [],
                          "thresholds": {"graduate_seen": 10, "graduate_kb": 6}}))
        sys.exit(0)
