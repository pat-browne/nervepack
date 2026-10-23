#!/usr/bin/env python3
"""One-time, idempotent migration: memory/playbooks + memory/strategies -> one
memory/lessons layer, per docs/superpowers/specs/2026-07-02-lessons-layer-merge-
design.md ("The entity" / "Migration"). stdlib only.

Usage: np-migrate-lessons.py <content_root>
       np-migrate-lessons.py --bodies <content_root>

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

--bodies mode (opt-in): rewrites legacy Symptom/Why/Do/Avoid and Title/When/Do
bodies in memory/lessons/*.md to one paired-rule line per entry under an
objective heading (`- DON'T x -> DO y -- **when** .. -- **why** .. [[episodic/t]]`).
Frontmatter (incl. enforce:) is kept byte-for-byte; the verbatim legacy body is
filed in memory/episodic/<topic>.md under a "migrated evidence" section. Every
converted file must pass np_lesson_format.lint or nothing is written. Entries
already in paired form are untouched, so a re-run is a no-op.

Idempotent: once memory/playbooks and memory/strategies are both gone (this
script's own doing, or because they never existed), re-running is a no-op
success -- memory/lessons is left exactly as it is.
"""
import datetime
import importlib.util
import os
import re
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


KNOWN_TOP_KEYS = {
    "name", "status", "seen", "last_updated", "wiki", "kind", "enforce",
    "topic_triggers",
}
KNOWN_ENFORCE_KEYS = {"tool_match", "gate", "tool_name_match", "topic_triggers"}


def _build_lesson(top, enforce, kind, path):
    for req in ("name", "status", "seen", "last_updated"):
        if req not in top:
            raise ParseError("%s: missing required field %r" % (path, req))
    wiki = top.get("wiki", "[]")
    # Lossless: any top-level key outside the known schema rides along
    # verbatim rather than being silently dropped.
    extra_top = [(k, v) for k, v in top.items() if k not in KNOWN_TOP_KEYS]

    if kind == "playbook":
        provenance = "failure"
        if enforce is None:
            raise ParseError("%s: playbook missing enforce: block" % path)
        if "topic_triggers" not in enforce:
            raise ParseError(
                "%s: playbook enforce: block missing topic_triggers" % path)
        # Fail closed: a present enforce: block missing tool_match or gate
        # must abort the migration rather than fabricate a default -- a
        # fabricated default would silently change what the entry's
        # enforcement does once wired to the live guard.
        if "tool_match" not in enforce or "gate" not in enforce:
            raise ParseError(
                "%s: playbook enforce: block missing tool_match and/or gate"
                % path)
        topic_triggers = enforce["topic_triggers"]
        new_enforce = {
            "tool_match": enforce["tool_match"],
            "gate": enforce["gate"],
        }
        if "tool_name_match" in enforce:
            new_enforce["tool_name_match"] = enforce["tool_name_match"]
        # Lossless: any enforce sub-key outside the known schema rides along
        # verbatim too.
        new_enforce["_extra"] = [
            (k, v) for k, v in enforce.items() if k not in KNOWN_ENFORCE_KEYS
        ]
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
        "extra_top": extra_top,
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
        for key, val in lesson["enforce"].get("_extra", []):
            lines.append("  %s: %s" % (key, val))
    for key, val in lesson["extra_top"]:
        lines.append("%s: %s" % (key, val))
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


def _main_merge(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: np-migrate-lessons.py [--bodies] <content_root>\n")
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


# ---------------------------------------------------------------------------
# --bodies mode: legacy Symptom/Why/Do/Avoid + Title/When/Do bodies in
# memory/lessons/*.md -> one paired-rule line per entry (change spec 0093).
# Frontmatter is kept byte-for-byte; the verbatim legacy body moves to
# memory/episodic/<topic>.md. Fail-safe: all computed in memory, linted, and
# only then written.
# ---------------------------------------------------------------------------

_FIELD_RE = re.compile(
    r"^\*\*(Symptom|Why|Do|Avoid|Title|When):\*{0,2}\s*(.*)$")
_SENT_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'(\[])")


def _load_format():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "np_lesson_format.py")
    spec = importlib.util.spec_from_file_location("np_lesson_format", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _split_entries(text, path):
    """-> list of {"head": str (frontmatter incl. both --- lines), "body": str}."""
    entries = []
    state = 0  # 0 outside, 1 in frontmatter, 2 in body
    lines = text.splitlines(keepends=True)
    skip_to = 0
    for i, line in enumerate(lines):
        if i < skip_to:
            continue
        stacked = (_stacked_keys(lines, i + 1)
                   if line.rstrip("\r\n") == "---" and state == 2 else None)
        if stacked:
            # A bare `---` between bodies (the shape §5b used to ask for),
            # optionally led by partial keys: the stacked entry inherits the
            # first entry's frontmatter, with its own provenance.
            keys, body_start = stacked
            entries.append({"head": _stacked_head(entries[0]["head"], keys, lines, body_start),
                            "body": ""})
            skip_to = body_start
        elif line.rstrip("\r\n") == "---" and state != 1:
            entries.append({"head": line, "body": ""})
            state = 1
        elif line.rstrip("\r\n") == "---":
            entries[-1]["head"] += line
            state = 2
        elif state == 1:
            entries[-1]["head"] += line
        elif state == 2:
            entries[-1]["body"] += line
        elif line.strip():
            raise ParseError("%s: text before first frontmatter" % path)
    if state == 1:
        raise ParseError("%s: unterminated frontmatter" % path)
    return entries


def _stacked_keys(lines, start):
    """After a bare `---` inside a body: -> (keys, body_start) when what follows
    is a stacked entry (body text, optionally led by `key: value` lines with no
    closing `---`), else None (a real frontmatter block, or nothing at all)."""
    keys = {}
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines):
        m = re.match(r"^([a-z_]+):[ \t]*(.*?)\s*$", lines[i])
        if not m:
            break
        keys[m.group(1)] = m.group(2)
        i += 1
    if i < len(lines) and lines[i].rstrip("\r\n") == "---":
        if keys:
            return None  # a real frontmatter block
        return _stacked_keys(lines, i + 1)  # a doubled separator
    if i >= len(lines) or not any(l.strip() for l in lines[i:]):
        return None
    return keys, i


def _stacked_head(first_head, keys, lines, start):
    body = []
    for line in lines[start:]:
        if line.rstrip("\r\n") == "---":
            break
        body.append(line)
    prov = keys.get("provenance") or (
        "success" if re.search(r"^\*\*Title:", "".join(body), re.M) else "failure")
    head = re.sub(r"^provenance:.*$", "provenance: " + prov, first_head, count=1, flags=re.M)
    # An enforce block gates the tool call for the entry that earned it only.
    return re.sub(r"^enforce:\n(?:[ \t]+.*\n)*", "", head, flags=re.M)


def _head_value(head, key):
    m = re.search(r"^%s:[ \t]*(.*?)[ \t]*$" % re.escape(key), head, re.M)
    if not m:
        m = re.search(r"^[ \t]+%s:[ \t]*(.*?)[ \t]*$" % re.escape(key), head, re.M)
    return m.group(1) if m else ""


def _legacy_fields(body):
    fields = {}
    cur = None
    for line in body.split("\n"):
        m = _FIELD_RE.match(line)
        if m:
            cur = m.group(1)
            fields[cur] = m.group(2).strip()
        elif cur is not None and line.strip():
            fields[cur] = (fields[cur] + " " + line.strip()).strip()
        else:
            cur = None
    return fields


def _first_sentence(val):
    val = _SENT_END_RE.split(val.strip(), 1)[0].strip()
    return val.rstrip(".").strip()


def _shorten(fmt, fields, max_chars):
    """Cap every field at one shared length, the largest cap that fits the rule
    into max_chars, cutting at a word boundary with a trailing ellipsis. An
    even cap keeps each field readable; trimming the longest field first cut
    some fields to a single character when the overflow exceeded its length."""
    if len(fmt(fields)) <= max_chars:
        return fmt(fields)

    def capped(cap):
        out = {}
        for k, v in fields.items():
            if len(v) <= cap:
                out[k] = v
            else:
                cut = v[:cap].rsplit(" ", 1)[0] if " " in v[:cap] else v[:cap]
                out[k] = cut.rstrip(" ,;:-") + "\u2026"
        return out

    lo, hi = 1, max(len(v) for v in fields.values())
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(fmt(capped(mid))) <= max_chars:
            lo = mid
        else:
            hi = mid - 1
    return fmt(capped(lo))


def _convert_body(entry, topic, path, fmtmod):
    """-> (new_body, verbatim_legacy_body) or None if nothing to convert."""
    body = entry["body"]
    if not any(fmtmod.LEGACY_HEADER_RE.match(l) for l in body.split("\n")):
        return None
    f = _legacy_fields(body)
    name = _head_value(entry["head"], "name")
    triggers = _head_value(entry["head"], "topic_triggers").strip()
    if triggers.startswith("[") and triggers.endswith("]"):
        triggers = triggers[1:-1].strip()
    scope = "working with %s" % (triggers or topic)
    link = "[[episodic/%s]]" % topic
    do = _first_sentence(f.get("Do", ""))
    if not do:
        raise ParseError("%s: entry %r has no Do field" % (path, name))
    if "Symptom" in f or "Avoid" in f or "Why" in f:
        heading = name
        avoid = _first_sentence(f.get("Avoid", ""))
        why = _first_sentence(f.get("Why", "")) or "it failed before"
        fields = {"avoid": avoid, "do": do, "when": scope, "why": why}

        def fmt(x):
            head = ("DON'T %s \u2192 DO %s" % (x.get("avoid"), x["do"])
                    if x.get("avoid") else "DO %s" % x["do"])
            return "- %s \u2014 **when** %s \u2014 **why** %s%s %s" % (
                head, x["when"], x["why"],
                "" if x["why"].endswith("\u2026") else ".", link)
        if not avoid:
            del fields["avoid"]
    else:
        heading = _first_sentence(f.get("Title", "")) or name
        when = _first_sentence(f.get("When", "")) or scope
        fields = {"do": do, "when": when}

        def fmt(x):
            return "- DO %s \u2014 **when** %s \u2014 **why** it worked before. %s" % (
                x["do"], x["when"], link)
    if not heading:
        raise ParseError("%s: entry has no name/title" % path)
    rule = _shorten(fmt, fields, fmtmod.MAX_CHARS)
    return "## %s\n%s\n" % (heading, rule), body


def _episodic_section(name, date, body):
    body = body if body.endswith("\n") else body + "\n"
    return "## [%s] lessons \u2014 migrated evidence: %s\n\n%s" % (date, name, body)


def migrate_bodies(root):
    fmtmod = _load_format()
    lessons_dir = os.path.join(root, "memory", "lessons")
    epi_dir = os.path.join(root, "memory", "episodic")
    if not os.path.isdir(lessons_dir):
        return
    out_lessons = {}   # path -> new text
    sections = {}      # topic -> [(date, section text)]
    for fname in sorted(os.listdir(lessons_dir)):
        if not fname.endswith(".md") or fname in SKIP_NAMES or fname.startswith("."):
            continue
        path = os.path.join(lessons_dir, fname)
        if not os.path.isfile(path):
            continue
        topic = fname[:-3]
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        entries = _split_entries(text, path)
        changed = False
        parts = []
        for e in entries:
            res = _convert_body(e, topic, path, fmtmod)
            if res is None:
                parts.append(e["head"] + e["body"])
                continue
            new_body, legacy = res
            changed = True
            date = (_head_value(e["head"], "last_updated")
                    or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"))
            name = _head_value(e["head"], "name")
            sections.setdefault(topic, []).append(
                (date, _episodic_section(name, date, legacy)))
            parts.append(e["head"] + new_body)
        if not changed:
            continue
        new_text = "".join(parts)
        findings = fmtmod.lint(new_text)
        if findings or len(fmtmod.parse(new_text)) != len(entries):
            raise ParseError("%s: converted file fails lint: %s" % (
                path, ", ".join("%s@%d" % (x.code, x.line) for x in findings)
                or "entry count changed"))
        out_lessons[path] = new_text

    out_epi = {}
    for topic, secs in sections.items():
        epath = os.path.join(epi_dir, topic + ".md")
        block = "".join(s for _, s in secs)
        if os.path.isfile(epath):
            with open(epath, encoding="utf-8") as fh:
                etext = fh.read()
            fm_block, rest = _split_frontmatter(etext, epath)
            head = etext[:len(etext) - len(rest)]
            out_epi[epath] = head + block + ("\n" + rest if rest.strip() else rest)
        else:
            date = max(d for d, _ in secs)
            out_epi[epath] = (
                "---\nname: %s\nkind: episodic\nlast_updated: %s\n"
                "wiki: []\nprojects: []\n---\n" % (topic, date)) + block

    # All computed and linted; only now touch the disk.
    if out_epi:
        os.makedirs(epi_dir, exist_ok=True)
    for p, t in list(out_epi.items()) + list(out_lessons.items()):
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(t)


def main(argv):
    if len(argv) == 3 and argv[1] == "--bodies":
        try:
            migrate_bodies(argv[2])
        except (ParseError, OSError) as exc:
            sys.stderr.write("np-migrate-lessons: %s\n" % exc)
            return 1
        return 0
    return _main_merge(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
