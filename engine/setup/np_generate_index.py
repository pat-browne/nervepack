"""Bash-free port of 60-generate-index.sh — regenerate the skill INDEX.md from
SKILL.md frontmatter (phase 17 of the bash->Python CLI migration).

Split-layout aware (engine repo + content overlay), byte-parity with the bash it
replaces:
  - The COMMITTED engine index (<engine>/INDEX.md) lists ENGINE skills ONLY — the
    publishable surface, pii-guarded.
  - In a split layout a MERGED index (engine + overlay, overlay-wins on a name
    clash; team layers appended highest-precedence-last when the `team` toggle is
    on) is also written to the overlay (<overlay>/INDEX.md) for local discovery.
  - In the legacy single-repo layout (content == engine) only the engine index is
    written (no second write).

STRAY-WRITE GUARD (past agents corrupted ~/Code/nervepack + ~/Code/nervepack-content
by running the bash against the real repo): the engine root is resolved from
NP_DIR / NERVEPACK / this file's own location (NEVER an unconditional
$HOME/Code/nervepack default), and the overlay via np_content EXACTLY as the bash
did. It writes ONLY to the resolved engine + overlay roots. Every test MUST run
hermetically (temp NP_DIR + NP_CONTENT_DIR) so a test run never regenerates the
real repo's INDEX.md. stdlib only.
"""
import os
import sys
# self-bootstrap (phase 20b-2): np_toggle/np_content/np_model and the other library
# modules were relocated into engine/nervepack_engine/; add that package dir so this
# script's flat imports of them resolve whether run standalone or imported.
_ENGINE_PKG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nervepack_engine"))
if _ENGINE_PKG not in sys.path:
    sys.path.insert(0, _ENGINE_PKG)

import os
import re
import sys

import np_content
import np_layout
import np_toggle

_HERE = os.path.dirname(os.path.abspath(__file__))


def _engine_root(np_dir=None):
    """The engine repo root. Resolution (safe — never an unconditional
    $HOME/Code/nervepack): explicit arg -> NP_DIR -> NERVEPACK -> this file's repo
    root (engine/setup is two levels below the root)."""
    return (np_dir or os.environ.get("NP_DIR") or os.environ.get("NERVEPACK")
            or os.path.dirname(os.path.dirname(_HERE)))


def _overlay_root(engine_root):
    """The content overlay root, matching what the bash's `np_content_dir` yields
    when 60-generate-index.sh is *run from* `engine_root`: an explicit env/config
    overlay is honored; the implicit default resolves to `engine_root` itself (not
    this module's own location), so a split layout is detected by env/config only."""
    d = np_content.content_dir()
    if not d or np_content.content_origin() == "default":
        return engine_root
    return d


def _extract(skill_file):
    """Return (name, description, line_count) for a SKILL.md, mirroring the bash
    awk: frontmatter is delimited by lines that are exactly '---'; the last in-fm
    'name:'/'description:' line wins; '|' is escaped; line_count is the file's total
    line count (awk NR)."""
    name = ""
    desc = ""
    in_fm = False
    try:
        with open(skill_file, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
    except OSError:
        return "", "", 0
    lines = data.splitlines()
    for line in lines:
        if line == "---":
            in_fm = not in_fm
            continue
        if in_fm and line.startswith("name:"):
            name = line[len("name:"):].lstrip(" \t")
        elif in_fm and line.startswith("description:"):
            desc = line[len("description:"):].lstrip(" \t")
    name = name.replace("|", "\\|")
    desc = desc.replace("|", "\\|")
    return name, desc, len(lines)


def _skill_map(bases):
    """Deduped name->dir across `bases`, later wins on a name clash (parallel to
    the bash `_idx_upsert`). Only immediate subdirectories of each base count."""
    names = []
    dirs = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            d = os.path.join(base, entry)
            if not os.path.isdir(d):
                continue
            if entry in names:
                dirs[names.index(entry)] = d
            else:
                names.append(entry)
                dirs.append(d)
    return list(zip(names, dirs))


def _existing_rows(out_file):
    """name -> row line, parsed from an existing INDEX.md skill table.

    Only rows of the exact generated shape `| [<name>](skills/<name>/SKILL.md) | …`
    are recognized, so hand-written prose and the archive footer are never mistaken
    for rows."""
    rows = {}
    try:
        with open(out_file, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.startswith("| ["):
            continue
        m = re.match(r"\| \[([^\]]+)\]\(skills/([^/]+)/SKILL\.md\) \|", line)
        if m:
            rows[m.group(2)] = line
    return rows


def _render_index(out_file, bases, archive_manifest, preserve_reason=""):
    """Write the INDEX.md at `out_file` from the skills under `bases` (precedence:
    later wins). Byte-parity with the bash render_index (header, sorted rows,
    archive footer)."""
    header = [
        "# nervepack — skill index",
        "",
        "Auto-generated by `cli.py setup generate-index` (engine/setup/np_generate_index.py).",
        "Don't edit by hand. Re-runs automatically inside `cli.py setup link-skills`.",
        "",
        "**Read this before adding a new skill** — find existing skills to",
        "extend rather than create overlapping duplicates.",
        "",
        "| Skill | Lines | Description |",
        "|---|---:|---|",
    ]
    rows = []
    produced = set()
    for name, d in _skill_map(bases):
        skill_file = os.path.join(d, "SKILL.md")
        if not os.path.isfile(skill_file):
            continue
        fm_name, fm_desc, lines = _extract(skill_file)
        if not fm_name:
            fm_name = name
        if not fm_desc:
            fm_desc = "_(no description in frontmatter)_"
        if fm_name != name:
            fm_name = name + " ⚠"
        rows.append("| [%s](skills/%s/SKILL.md) | %s | %s |" % (fm_name, name, lines, fm_desc))
        produced.add(name)

    # nervepack#241: an ENABLED layer this machine cannot resolve contributes no
    # bases, so an authoritative regen would DELETE its rows from a shared committed
    # file — silently, and a cron would push it. Carry those rows over instead. This
    # is gated on the unresolvable-layer condition, never unconditional: with every
    # enabled layer resolvable, the regen stays authoritative and a genuinely deleted
    # skill is still pruned. Worst case is a stale row until a machine that can see
    # the layer regenerates, which is visible and self-correcting; deletion is not.
    if preserve_reason:
        orphaned = {n: line for n, line in _existing_rows(out_file).items()
                    if n not in produced}
        if orphaned:
            rows.extend(orphaned[n] for n in sorted(orphaned))
            sys.stderr.write(
                "np-generate-index: %s — preserving %d existing row(s) rather than "
                "deleting them: %s\n"
                % (preserve_reason, len(orphaned), ", ".join(sorted(orphaned))))
    rows.sort()

    footer = ["", "## Archived skills", ""]
    if os.path.isfile(archive_manifest) and os.path.getsize(archive_manifest) > 0:
        footer.append("See [archive/MANIFEST.md](archive/MANIFEST.md).")
    else:
        footer.append("_(none yet)_")

    text = "\n".join(header + rows + footer) + "\n"
    tmp = out_file + ".tmp-npidx"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, out_file)
    return out_file


def _excerpt(body, limit=160):
    """The first line of real prose in a page body, truncated.

    Curated wiki pages carry name/kind/last_updated but rarely a `description:`, so
    a description-only column reads "(no description)" for every row and the index
    is useless for discovery. Fall back to what the page actually opens with."""
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ">", "|", "---", "```", "<!--")):
            continue
        if len(line) > limit:
            line = line[:limit].rstrip() + "…"
        return line
    return ""


def _page_meta(path):
    """(kind, description) for a knowledge page. `description:` wins; otherwise the
    page's opening prose line."""
    kind = ""
    desc = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError:
        return "", ""
    if not head.startswith("---"):
        return "", ""
    parts = head.split("---", 2)
    if len(parts) < 3:
        return "", ""
    for line in parts[1].splitlines():
        if line.startswith("kind:"):
            kind = line[len("kind:"):].strip()
        elif line.startswith("description:"):
            desc = line[len("description:"):].strip()
    return kind, desc or _excerpt(parts[2])


def _knowledge_rows(root):
    """Markdown rows for every page reachable through the layer's knowledge and
    reference routes (nervepack#234).

    Follows the layer's DECLARED routes, so a layer that keeps knowledge in notes/
    indexes exactly as one that uses wiki/. Without this the index lists skills
    only, a page is findable only by knowing its directory, and directory structure
    stays a contract in practice no matter what the manifest says."""
    try:
        layout, _source = np_layout.resolve(root)
    except np_layout.LayoutError:
        return []
    dirs = set()
    for kind in ("knowledge", "reference"):
        spec = (layout.get("routes") or {}).get(kind)
        if not isinstance(spec, dict):
            continue
        entries = spec.get("variants") if "variants" in spec else [spec]
        for e in entries or []:
            head = ((e or {}).get("path") or "").split("{", 1)[0].rstrip("/")
            if head:
                dirs.add(head)
    rows = []
    for d in sorted(dirs):
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in sorted(dirnames) if not x.startswith(".")]
            for f in sorted(filenames):
                if not f.endswith(".md") or f == "README.md":
                    continue
                full = os.path.join(dirpath, f)
                kind, desc = _page_meta(full)
                if not kind:
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                rows.append("| [%s](%s) | `%s` | %s | %s |"
                            % (f[:-3], rel, rel, kind,
                               (desc or "_(no description)_").replace("|", "\\|")))
    return sorted(set(rows))


def _append_knowledge(path, rows):
    """Append the Knowledge section to an already-written index."""
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n## Knowledge\n\n")
        fh.write("Pages reachable through this layer's declared routes\n")
        fh.write("(`cli.py layout show`). Discovery reads this table, not the\n")
        fh.write("directory tree.\n\n")
        fh.write("| Page | Path | Kind | Description |\n|---|---|---|---|\n")
        fh.write("\n".join(rows) + "\n")


def generate(np_dir=None, out=None):
    """Regenerate the engine (and, in a split layout, the merged overlay) INDEX.md.
    Returns 0. Writes ONLY to the resolved engine + overlay roots."""
    out = out or sys.stdout
    engine_root = _engine_root(np_dir)
    engine_skills = os.path.join(engine_root, "skills")
    overlay_root = _overlay_root(engine_root)
    overlay_skills = os.path.join(overlay_root, "skills")
    archive_manifest = os.path.join(engine_root, "archive", "MANIFEST.md")

    if not os.path.isdir(engine_skills) and not os.path.isdir(overlay_skills):
        sys.stderr.write("no skills/ dir at %s or %s\n" % (engine_skills, overlay_skills))
        return 1

    # Committed engine index: ENGINE skills only (publishable surface, pii-guarded).
    written = _render_index(os.path.join(engine_root, "INDEX.md"),
                            [engine_skills], archive_manifest)
    out.write("wrote %s\n" % written)

    # Split layout: also write the merged (engine + overlay [+ team]) index into
    # the overlay for local discovery. Skip when content == engine (legacy single
    # repo) — the engine index already covers the full set there.
    if overlay_root != engine_root:
        merged_bases = [engine_skills, overlay_skills]
        if np_toggle.enabled("team"):
            for t in reversed(np_content.team_dirs()):
                merged_bases.append(os.path.join(t, "skills"))
        # Preservation applies to the MERGED index only. The engine index lists
        # engine skills exclusively, so no unresolvable layer can contribute to it.
        written = _render_index(os.path.join(overlay_root, "INDEX.md"),
                                merged_bases, archive_manifest,
                                preserve_reason=np_content.unresolved_layers())
        # The engine INDEX.md stays skills-only (publishable, pii-guarded); the
        # merged overlay index also carries the knowledge tree.
        rows = _knowledge_rows(overlay_root)
        if rows:
            _append_knowledge(written, rows)
        out.write("wrote %s\n" % written)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(generate())
