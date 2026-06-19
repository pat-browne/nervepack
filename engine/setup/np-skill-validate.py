#!/usr/bin/env python3
"""Validate-or-abort gate for a skill split. Compares the edited skill against its
pre-edit version; exit 0 = safe to keep, non-zero + reason on stderr = revert.
Deterministic, no LLM.

Usage: np-skill-validate.py <skill_dir> <original_skill_md>
  <skill_dir>          working-tree skill dir (edited SKILL.md + references/)
  <original_skill_md>  path to the pre-edit SKILL.md (cron writes HEAD version here)

Threshold via env SKILL_SPLIT_KB (default 8).
"""
import os
import re
import sys

LINK = re.compile(r"\[\[([^\]]+)\]\]")
FENCE = re.compile(r"```.*?```", re.DOTALL)


def _links(text):
    """Cross-links in prose only — fenced code blocks are stripped first so a bash
    `[[ -z "$x" ]]` expression isn't mistaken for an `[[cross-link]]`. Applied to
    both before/after symmetrically, so a code example moved into a reference never
    triggers a false 'dropped link' revert."""
    return set(LINK.findall(FENCE.sub("", text)))


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _field(text, field):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if line.startswith(field + ":"):
            return line[len(field) + 1:].strip()
    return None


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def fail(msg):
    sys.stderr.write("skill-validate: " + msg + "\n")
    return 1


def main(argv):
    if len(argv) < 3:
        return fail("usage: np-skill-validate.py <skill_dir> <original_skill_md>")
    skill_dir, original = argv[1], argv[2]
    skill_md = os.path.join(skill_dir, "SKILL.md")
    refs_dir = os.path.join(skill_dir, "references")
    split_b = _int_env("SKILL_SPLIT_KB", 8) * 1024

    try:
        after, before = _read(skill_md), _read(original)
    except OSError as exc:
        return fail("cannot read skill files: %s" % exc)

    # 1. body now under the hard threshold
    if len(after.encode("utf-8")) > split_b:
        return fail("body still over %d bytes" % split_b)
    # 2. frontmatter name + description unchanged
    for field in ("name", "description"):
        if _field(after, field) != _field(before, field):
            return fail("frontmatter %s changed" % field)
    # 3. no [[link]] dropped (after, across body + references, must cover before)
    after_links = _links(after)
    ref_md = []
    if os.path.isdir(refs_dir):
        ref_md = [f for f in os.listdir(refs_dir) if f.endswith(".md")]
        for fn in ref_md:
            try:
                after_links |= _links(_read(os.path.join(refs_dir, fn)))
            except OSError:
                pass
    missing = _links(before) - after_links
    if missing:
        return fail("dropped cross-links: %s" % ",".join(sorted(missing)))
    # 4. references/ non-empty + body points to it
    nonempty = any(os.path.getsize(os.path.join(refs_dir, f)) > 0 for f in ref_md)
    if not nonempty:
        return fail("references/ missing or empty")
    if "references/" not in after:
        return fail("body has no pointer to references/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
