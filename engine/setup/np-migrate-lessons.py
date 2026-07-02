#!/usr/bin/env python3
"""One-time, idempotent migration: memory/playbooks + memory/strategies -> one
memory/lessons layer, per docs/superpowers/specs/2026-07-02-lessons-layer-merge-
design.md ("The entity" / "Migration"). stdlib only.

Usage: np-migrate-lessons.py <content_root>

For each old entry:
  - kind: playbook -> kind: lesson, provenance: failure, keep the enforce
    block (tool_match, gate, tool_name_match if present), hoist topic_triggers
    out of the enforce block to the top level.
  - kind: strategy -> kind: lesson, provenance: success, no enforce block,
    topic_triggers stays at the top level (it already was).
  - name/status/seen/last_updated/wiki carry over unchanged; the body is
    preserved byte-for-byte.
  - A topic present in BOTH playbooks and strategies merges into one
    memory/lessons/<topic>.md, both entries back to back (the second entry's
    own opening `---` delimiter is the separator).

Regenerates memory/lessons/INDEX.md in the same table shape the PreToolUse
guard's Phase-1 parser already reads (`while IFS='|' read -r _ topic
tool_match gate _rest`): a leading `|`, header row, separator row, then
`| topic | tool_match | gate | topic_triggers |` data rows. Advisory entries
(no/empty tool_match) get an empty tool_match cell.

Fail-safe: every source file is parsed and every output rendered fully in
memory FIRST; nothing is written to disk unless ALL of it parses cleanly. Any
parse failure aborts the whole migration (source dirs untouched) with a
message on stderr and a non-zero exit.

Idempotent: once memory/playbooks and memory/strategies are both gone (this
script's own doing, or because they never existed), re-running is a no-op
success -- memory/lessons is left exactly as it is.
"""
import os
import shutil
import sys

SKIP_NAMES = {"INDEX.md", "README.md"}


class ParseError(Exception):
    pass


def _split_frontmatter(text, path):
    if not text.startswith("---\n"):
        raise ParseError("%s: missing frontmatter delimiter" % path)
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ParseError("%s: unterminated frontmatter" % path)
    fm_block = text[4:end]
    body = text[end + len("\n---\n"):]
    return fm_block, body


def _parse_frontmatter(fm_block, path):
    """Returns (top_level dict[str,str], enforce dict[str,str] or None). Only
    'enforce:' carries a nested (2-space-indented) block in this schema."""
    top = {}
    enforce = None
    cur = "top"
    for raw_line in fm_block.split("\n"):
        if not raw_line.strip():
            continue
        if raw_line.startswith(" "):
            if cur != "enforce":
                raise ParseError(
                    "%s: unexpected indented line outside enforce: block: %r"
                    % (path, raw_line))
            key, sep, val = raw_line.strip().partition(":")
            if not sep:
                raise ParseError("%s: malformed enforce line: %r" % (path, raw_line))
            enforce[key.strip()] = val.strip()
            continue
        key, sep, val = raw_line.partition(":")
        if not sep:
            raise ParseError("%s: malformed frontmatter line: %r" % (path, raw_line))
        key = key.strip()
        val = val.strip()
        if key == "enforce":
            enforce = {}
            cur = "enforce"
            continue
        cur = "top"
        top[key] = val
    return top, enforce


def _build_lesson(top, enforce, kind, path):
    for req in ("name", "status", "seen", "last_updated"):
        if req not in top:
            raise ParseError("%s: missing required field %r" % (path, req))
    wiki = top.get("wiki", "[]")

    if kind == "playbook":
        provenance = "failure"
        if enforce is None:
            raise ParseError("%s: playbook missing enforce: block" % path)
        if "topic_triggers" not in enforce:
            raise ParseError(
                "%s: playbook enforce: block missing topic_triggers" % path)
        topic_triggers = enforce["topic_triggers"]
        new_enforce = {
            "tool_match": enforce.get("tool_match", '""'),
            "gate": enforce.get("gate", "warn"),
        }
        if "tool_name_match" in enforce:
            new_enforce["tool_name_match"] = enforce["tool_name_match"]
    elif kind == "strategy":
        provenance = "success"
        if "topic_triggers" not in top:
            raise ParseError("%s: strategy missing topic_triggers" % path)
        topic_triggers = top["topic_triggers"]
        new_enforce = None
    else:
        raise ParseError("%s: unknown kind %r (expected playbook/strategy)" % (path, kind))

    return {
        "name": top["name"],
        "provenance": provenance,
        "status": top["status"],
        "seen": top["seen"],
        "last_updated": top["last_updated"],
        "topic_triggers": topic_triggers,
        "enforce": new_enforce,
        "wiki": wiki,
    }


def _load_dir(dirpath, kind):
    """Returns (dict topic->lesson, ordered list of topics). Empty/absent dir
    -> ({}, [])."""
    entries = {}
    order = []
    if not os.path.isdir(dirpath):
        return entries, order
    for name in sorted(os.listdir(dirpath)):
        if not name.endswith(".md") or name in SKIP_NAMES or name.startswith("."):
            continue
        path = os.path.join(dirpath, name)
        if not os.path.isfile(path):
            continue
        topic = name[:-3]
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        fm_block, body = _split_frontmatter(text, path)
        top, enforce = _parse_frontmatter(fm_block, path)
        actual_kind = top.get("kind")
        if actual_kind != kind:
            raise ParseError(
                "%s: expected kind: %s, got %r" % (path, kind, actual_kind))
        lesson = _build_lesson(top, enforce, kind, path)
        lesson["body"] = body
        entries[topic] = lesson
        order.append(topic)
    return entries, order


def _render_entry(lesson):
    lines = [
        "---",
        "name: %s" % lesson["name"],
        "kind: lesson",
        "provenance: %s" % lesson["provenance"],
        "status: %s" % lesson["status"],
        "seen: %s" % lesson["seen"],
        "last_updated: %s" % lesson["last_updated"],
        "topic_triggers: %s" % lesson["topic_triggers"],
    ]
    if lesson["enforce"] is not None:
        lines.append("enforce:")
        lines.append("  tool_match: %s" % lesson["enforce"]["tool_match"])
        lines.append("  gate: %s" % lesson["enforce"]["gate"])
        if "tool_name_match" in lesson["enforce"]:
            lines.append("  tool_name_match: %s" % lesson["enforce"]["tool_name_match"])
    lines.append("wiki: %s" % lesson["wiki"])
    lines.append("---")
    return "\n".join(lines) + "\n" + lesson["body"]


def _unquote(raw):
    """YAML-double-quoted-string -> plain regex/text, for the INDEX.md cell
    (matches the existing playbooks/INDEX.md convention: 'zip.*\\\\$\\\\(' ->
    'zip.*\\$\\('). Preserved verbatim (quotes and all) inside the lesson file
    itself -- this unquoting is ONLY for the generated table cell."""
    s = raw.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace("\\\\", "\\")
    return s


def _list_inner(raw):
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        return s[1:-1].strip()
    return s


def _render_index(rows):
    lines = [
        "# lessons — index",
        "",
        "Auto-regenerated by the weekly `np-flow-episodic-maintain` agent. Don't edit by hand.",
        "",
        "Unified failure+success layer (was: playbooks + strategies). `tool_match`",
        "drives the `PreToolUse` guard; `topic_triggers` drives the `UserPromptSubmit`",
        "recall injection. Advisory entries (no/empty tool_match) carry an empty",
        "`tool_match` cell.",
        "",
        "| topic | tool_match | gate | topic_triggers |",
        "|---|---|---|---|",
    ]
    for topic, tool_match, gate, triggers in rows:
        lines.append("| %s | %s | %s | %s |" % (topic, tool_match, gate, triggers))
    return "\n".join(lines) + "\n"


def migrate(root):
    memory = os.path.join(root, "memory")
    pb_dir = os.path.join(memory, "playbooks")
    st_dir = os.path.join(memory, "strategies")
    lessons_dir = os.path.join(memory, "lessons")

    if not os.path.isdir(pb_dir) and not os.path.isdir(st_dir):
        return  # already migrated (or never had the old layers) -- no-op

    playbooks, pb_order = _load_dir(pb_dir, "playbook")
    strategies, st_order = _load_dir(st_dir, "strategy")

    topics = []
    seen_topics = set()
    for t in pb_order + st_order:
        if t not in seen_topics:
            seen_topics.add(t)
            topics.append(t)

    rendered = {}
    index_rows = []
    for topic in topics:
        pb = playbooks.get(topic)
        st = strategies.get(topic)
        parts = []
        if pb:
            parts.append(_render_entry(pb))
        if st:
            parts.append(_render_entry(st))
        rendered[topic] = "".join(parts)

        if pb:
            tool_match = _unquote(pb["enforce"]["tool_match"])
            gate = pb["enforce"]["gate"]
            triggers = _list_inner(pb["topic_triggers"])
        else:
            tool_match = ""
            gate = ""
            triggers = _list_inner(st["topic_triggers"])
        index_rows.append((topic, tool_match, gate, triggers))

    index_text = _render_index(index_rows)

    # Everything above is pure computation (no disk writes) -- a parse error
    # anywhere raises before this point, so nothing below ever runs.
    os.makedirs(lessons_dir, exist_ok=True)
    for topic, text in rendered.items():
        with open(os.path.join(lessons_dir, topic + ".md"), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(lessons_dir, "INDEX.md"), "w", encoding="utf-8") as fh:
        fh.write(index_text)

    shutil.rmtree(pb_dir, ignore_errors=True)
    shutil.rmtree(st_dir, ignore_errors=True)


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: np-migrate-lessons.py <content_root>\n")
        return 2
    root = argv[1]
    try:
        migrate(root)
    except ParseError as exc:
        sys.stderr.write("np-migrate-lessons: %s\n" % exc)
        return 1
    except OSError as exc:
        sys.stderr.write("np-migrate-lessons: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
