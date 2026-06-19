#!/usr/bin/env python3
"""Deterministic skill-budget detector for the daily skill-maintenance routine.

Scans <skills_dir>/*/SKILL.md and reports which exceed the hard split threshold,
which exceed the soft authoring target, and the always-loaded catalog token total
vs its budget. No LLM. Thresholds via env (the cron wrapper resolves them from
toggle params; tests set them directly), with built-in defaults:

    SKILL_SPLIT_KB    (default 8)     hard auto-split trigger
    SKILL_SOFT_KB     (default 6)     advisory authoring target
    SKILL_CATALOG_TOK (default 4000)  flat->tree restructure budget

Usage: np-skill-budget.py [skills_dir]   (default: <repo>/skills)
Emits one JSON object to stdout. Fail-open: on error, an empty report.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SKILLS = os.path.join(HERE, "..", "skills")


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _description(text):
    """Value of the frontmatter `description:` (first block); '' if none."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    for line in text[3:end].splitlines():
        if line.startswith("description:"):
            return line[len("description:"):].strip()
    return ""


def scan(skills_dir):
    split_kb = _int_env("SKILL_SPLIT_KB", 8)
    soft_kb = _int_env("SKILL_SOFT_KB", 6)
    catalog_tok = _int_env("SKILL_CATALOG_TOK", 4000)
    split_b, soft_b = split_kb * 1024, soft_kb * 1024

    split_candidates, soft_over, desc_chars = [], [], 0
    try:
        names = sorted(os.listdir(skills_dir))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(skills_dir, name, "SKILL.md")
        if not os.path.isfile(path):
            continue
        try:
            nbytes = os.path.getsize(path)
            with open(path, encoding="utf-8", errors="replace") as fh:
                desc_chars += len(_description(fh.read()))
        except OSError:
            continue
        if nbytes > split_b:
            split_candidates.append({"skill": name, "bytes": nbytes})
        elif nbytes > soft_b:
            soft_over.append({"skill": name, "bytes": nbytes})
    catalog_tokens = desc_chars // 4
    return {
        "split_candidates": split_candidates,
        "soft_over": soft_over,
        "catalog_tokens": catalog_tokens,
        "catalog_over": catalog_tokens > catalog_tok,
        "thresholds": {"split_kb": split_kb, "soft_kb": soft_kb,
                       "catalog_tok": catalog_tok},
    }


def main(argv):
    skills_dir = argv[1] if len(argv) > 1 else DEFAULT_SKILLS
    print(json.dumps(scan(skills_dir), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:
        print(json.dumps({"split_candidates": [], "soft_over": [],
                          "catalog_tokens": 0, "catalog_over": False}))
        sys.exit(0)
