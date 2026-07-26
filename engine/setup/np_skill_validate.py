#!/usr/bin/env python3
"""Validate-or-abort gate for a skill split. Compares the edited skill against its
pre-edit version; exit 0 = safe to keep, non-zero + reason on stderr = revert.
Deterministic, no LLM.

Usage: np_skill_validate.py <skill_dir> <original_skill_md>
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


def _headings(text):
    """Markdown heading lines (`#`..`######`) in prose, with fenced code stripped
    first so a shell `# comment` inside a ```block isn't mistaken for a heading.
    Used for the content-conservation check: every pre-edit section heading must
    survive in the edited body or a reference file, proving a split RELOCATED the
    overflow rather than deleting it."""
    out = []
    for line in FENCE.sub("", text).splitlines():
        s = line.strip()
        if s.startswith("#"):
            out.append(s)
    return out


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


def validate(skill_dir, original):
    """Compare the edited skill against its pre-edit version. Returns (ok, reason)
    -- reason is "" when ok is True, else a human-readable cause for the caller to
    log/print. Deterministic, no LLM, never raises (a read failure is reported as
    a normal (False, reason) result, not an exception)."""
    skill_md = os.path.join(skill_dir, "SKILL.md")
    refs_dir = os.path.join(skill_dir, "references")
    split_b = _int_env("SKILL_SPLIT_KB", 8) * 1024

    try:
        after, before = _read(skill_md), _read(original)
    except OSError as exc:
        return False, "cannot read skill files: %s" % exc

    if len(after.encode("utf-8")) > split_b:
        return False, "body still over %d bytes" % split_b
    for field in ("name", "description"):
        if _field(after, field) != _field(before, field):
            return False, "frontmatter %s changed" % field
    after_links = _links(after)
    ref_texts = []
    ref_md = []
    if os.path.isdir(refs_dir):
        ref_md = [f for f in os.listdir(refs_dir) if f.endswith(".md")]
        for fn in ref_md:
            try:
                t = _read(os.path.join(refs_dir, fn))
            except OSError:
                continue
            ref_texts.append(t)
            after_links |= _links(t)
    missing = _links(before) - after_links
    if missing:
        return False, "dropped cross-links: %s" % ",".join(sorted(missing))
    # Content-conservation: a split must MOVE overflow into references/, not delete
    # it. Every heading present in the pre-edit body must survive in the edited body
    # or a reference file; a truncating split that discards a section (dropping its
    # content to get under budget) is caught here even when references/ is non-empty.
    after_headings = set(_headings(after))
    for t in ref_texts:
        after_headings |= set(_headings(t))
    dropped = [h for h in _headings(before) if h not in after_headings]
    if dropped:
        return False, "dropped section(s) not relocated to references/: %s" % "; ".join(dropped[:3])
    nonempty = any(os.path.getsize(os.path.join(refs_dir, f)) > 0 for f in ref_md)
    if not nonempty:
        return False, "references/ missing or empty"
    if "references/" not in after:
        return False, "body has no pointer to references/"
    return True, ""


def fail(msg):
    sys.stderr.write("skill-validate: " + msg + "\n")
    return 1


def main(argv):
    if len(argv) < 3:
        return fail("usage: np_skill_validate.py <skill_dir> <original_skill_md>")
    ok, reason = validate(argv[1], argv[2])
    if not ok:
        return fail(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
