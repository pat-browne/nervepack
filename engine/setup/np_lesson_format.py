#!/usr/bin/env python3
"""Paired-rule lesson format: parser + lint (change spec 0093). stdlib only.

A lesson file (`memory/lessons/<topic>.md`) holds one or more frontmatter+body
entries (a topic may stack a failure and a success entry). Each body is a set of
objective headings, each followed by one paired-rule line per lesson:

    ## <objective>
    - DON'T <x> → DO <y> — **when** <scope> — **why** <reason>. [[episodic/<topic>]]

A lone `DO` is allowed (a win with no real anti-pattern); a lone `DON'T` is a
finding. An entry may wrap onto an indented continuation line but stays within
MAX_LINES rendered lines and about MAX_CHARS characters. Narrative belongs in
`memory/episodic/`, one backlink away -- not in the lesson.

The legacy Symptom/Why/Do/Avoid and Title/When/Do bodies still parse (recall
reads both during migration) but lint flags them `legacy-format`.

Usage: np_lesson_format.py lint <file>...   (exit 1 on any finding)
"""
import collections
import os
import re
import sys

MAX_CHARS = 320
MAX_LINES = 2

LEGACY_HEADER_RE = re.compile(r'^\*\*(Symptom|Why|Do|Avoid|Title|When):')
_HEADING_RE = re.compile(r'^##\s+(.+?)\s*$')
_SEP = r'\s+[—–-]\s+'
_WHEN_RE = re.compile(_SEP + r'\*\*when\*\*\s*', re.IGNORECASE)
_WHY_RE = re.compile(_SEP + r'\*\*why\*\*\s*', re.IGNORECASE)
_DONT_RE = re.compile(r"^DON['’]T\s+(.*?)(?:\s+(?:→|->)\s+DO\s+(.*))?$", re.DOTALL)
_DO_RE = re.compile(r'^DO\s+(.*)$', re.DOTALL)
_LINK_RE = re.compile(r'\[\[([^\]]+)\]\]')

Rule = collections.namedtuple(
    "Rule", "objective dont do when why links text line nlines")
Block = collections.namedtuple("Block", "provenance rules legacy stray line")
Finding = collections.namedtuple("Finding", "code line message")


def _parse_rule(objective, text, line, nlines):
    """Split one rule entry (continuation lines already joined) into its parts."""
    body = text[2:].strip()
    links = _LINK_RE.findall(body)
    # Slice at each labelled marker, in whichever order they appear.
    marks = sorted((m.start(), m.end(), name) for name, m in
                   (("when", _WHEN_RE.search(body)), ("why", _WHY_RE.search(body))) if m)
    parts = {"when": "", "why": ""}
    for i, (_, end, name) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        parts[name] = body[end:stop].strip()
    when, why = parts["when"], parts["why"]
    if marks:
        body = body[:marks[0][0]]
    head = body.strip()
    dont = do = ""
    m = _DONT_RE.match(head)
    if m:
        dont, do = m.group(1).strip(), (m.group(2) or "").strip()
    else:
        m = _DO_RE.match(head)
        if m:
            do = m.group(1).strip()
    return Rule(objective, dont, do, when, why, links, text, line, nlines)


def _is_rule_start(line):
    return re.match(r"^- (DON['’]T|DO)\s", line) is not None


def parse(text):
    """Return a list of Block, one per frontmatter+body entry, in file order.

    Block.rules holds the paired-rule entries; Block.legacy the legacy
    `**Header:**` lines (first line of each field only); Block.stray the line
    numbers of body text that is neither a heading, a rule, nor legacy."""
    lines = text.split("\n")
    blocks = []
    c = 0
    cur = None
    objective = ""
    rule_lines = None  # (start_line, [text lines]) of the rule being collected

    def flush_rule():
        nonlocal rule_lines
        if rule_lines is not None and cur is not None:
            start, parts = rule_lines
            joined = " ".join(p.strip() for p in parts)
            cur["rules"].append(_parse_rule(objective, joined, start, len(parts)))
        rule_lines = None

    def flush_block():
        flush_rule()
        if cur is not None:
            blocks.append(Block(cur["prov"], cur["rules"], cur["legacy"],
                                cur["stray"], cur["line"]))

    for i, raw in enumerate(lines, 1):
        line = raw.rstrip("\r")
        if line == "---":
            c += 1
            if c % 2 == 1:
                flush_block()
                cur = {"prov": "", "rules": [], "legacy": [], "stray": [], "line": i}
                objective = ""
            continue
        if cur is None:
            continue
        if c % 2 == 1:
            if line.startswith("provenance:"):
                cur["prov"] = line[len("provenance:"):].strip()
            continue
        if rule_lines is not None and line[:1] in (" ", "\t") and line.strip():
            rule_lines[1].append(line)
            continue
        flush_rule()
        if not line.strip():
            continue
        m = _HEADING_RE.match(line)
        if m:
            objective = m.group(1)
        elif _is_rule_start(line):
            rule_lines = (i, [line])
        elif LEGACY_HEADER_RE.match(line):
            cur["legacy"].append(line)
        elif not line.startswith("#"):
            cur["stray"].append(i)
    flush_block()
    return blocks


def lint(text):
    """Return a list of Finding for a lesson file's text (empty = clean)."""
    findings = []
    for block in parse(text):
        if block.legacy:
            findings.append(Finding(
                "legacy-format", block.line,
                "Symptom/Why/Do/Avoid or Title/When/Do body; migrate to paired rules"))
        elif block.stray:
            findings.append(Finding(
                "legacy-format", block.stray[0],
                "body text outside a heading or DON'T/DO rule line"))
        for r in block.rules:
            if not r.when:
                findings.append(Finding("missing-when", r.line, "rule has no **when** scope"))
            if not r.why:
                findings.append(Finding("missing-why", r.line, "rule has no **why** reason"))
            if r.dont and not r.do:
                findings.append(Finding("lone-dont", r.line, "DON'T without a paired DO"))
            if len(r.text) > MAX_CHARS or r.nlines > MAX_LINES:
                findings.append(Finding(
                    "too-long", r.line,
                    "%d chars / %d lines (budget %d / %d)"
                    % (len(r.text), r.nlines, MAX_CHARS, MAX_LINES)))
    return findings


def render(block, suffix=""):
    """Injection text for a paired-rule block: each objective heading once (as
    `<objective><suffix>:`), then its rule lines with `[[...]]` backlinks
    stripped -- the evidence stays one lookup away, not in every prompt.
    Empty string when the block holds no rules."""
    out = []
    objective = None
    for r in block.rules:
        if r.objective != objective:
            objective = r.objective
            if objective:
                out.append(objective + suffix + ":")
        out.append(re.sub(r"\s+", " ", _LINK_RE.sub("", r.text)).rstrip())
    return "\n".join(out)


def main(argv):
    if len(argv) < 3 or argv[1] != "lint":
        sys.stderr.write("usage: np_lesson_format.py lint <file>...\n")
        return 2
    bad = 0
    for path in argv[2:]:
        if os.path.basename(path) in ("INDEX.md", "README.md"):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            sys.stderr.write("%s: %s\n" % (path, exc))
            bad += 1
            continue
        for f in lint(text):
            print("%s:%d: %s: %s" % (path, f.line, f.code, f.message))
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
