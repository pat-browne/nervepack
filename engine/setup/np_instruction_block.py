"""Pure-Python port of np-instruction-block.sh -- manage nervepack's additive
@import block in a host instruction file (CLAUDE.md / AGENTS.md / a Cursor
rule). Additive, idempotent, removable: only the fenced block is ever
touched.

The marker text is deliberately kept byte-identical to the bash original,
including its now-stale mention of "np-instruction-block.sh remove" --
already-installed blocks on other machines have this exact text, and
remove() matches on exact line equality. See the phase-11 plan for the full
reasoning.
"""
import os

BEGIN = "<!-- nervepack:begin (managed — do not edit; remove via np-instruction-block.sh remove) -->"
END = "<!-- nervepack:end -->"
_DEFAULT_DIRECTIVE_PATH = os.path.join(
    os.environ.get("HOME") or os.path.expanduser("~"),
    "Code", "nervepack", "engine", "setup", "nervepack-session-directive.md")


def remove(file_path):
    if not file_path:
        raise ValueError("no file given")
    if not os.path.isfile(file_path):
        return
    with open(file_path, "r", encoding="utf-8") as fh:
        original_lines = fh.read().splitlines()

    out = []
    inblk = False
    buf = []
    for line in original_lines:
        if line == BEGIN:
            inblk = True
            buf = []
            continue
        if inblk and line == END:
            inblk = False
            continue
        if inblk:
            buf.append(line)
            continue
        out.append(line)
    if inblk:
        # Unterminated block (a lone/orphaned begin marker): put it back
        # exactly as found, matching the bash awk END{} fallback.
        out.append(BEGIN)
        out.extend(buf)

    with open(file_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + ("\n" if out else ""))


def install(file_path, directive_path=None):
    if not file_path:
        raise ValueError("no file given")
    directive_path = directive_path or os.environ.get("NP_DIRECTIVE_PATH") or _DEFAULT_DIRECTIVE_PATH

    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    if not os.path.isfile(file_path):
        open(file_path, "w").close()

    remove(file_path)  # strip any prior block (idempotent)

    with open(file_path, "r", encoding="utf-8") as fh:
        existing = fh.read()

    with open(file_path, "w", encoding="utf-8") as fh:
        fh.write(existing)
        # Bash: [[ -s "$file" ]] && printf '\n' -- an UNCONDITIONAL blank
        # separator line whenever the file is non-empty, regardless of
        # whether it already ends in a newline. Not "add a newline only if
        # missing" -- a file already ending in "\n" still gets a second,
        # blank line before the block.
        if existing:
            fh.write("\n")
        fh.write(BEGIN + "\n")
        fh.write("@%s\n" % directive_path)
        fh.write(END + "\n")


# Tagged blocks carry a body inline instead of an @import. They use their own
# markers, so they never collide with the directive block above.
def _tag_markers(tag):
    return ("<!-- nervepack:%s:begin (managed, do not edit, synced from the content overlay) -->" % tag,
            "<!-- nervepack:%s:end -->" % tag)


def _split_tagged(lines, tag):
    """(before, body_lines, after) around the tagged block, or None when absent."""
    begin, end = _tag_markers(tag)
    if begin not in lines:
        return None
    i = lines.index(begin)
    if end not in lines[i + 1:]:
        return None
    j = lines.index(end, i + 1)
    return lines[:i], lines[i + 1:j], lines[j + 1:]


def _read_lines(file_path):
    if not os.path.isfile(file_path):
        return []
    with open(file_path, "r", encoding="utf-8") as fh:
        return fh.read().splitlines()


def _write_lines(file_path, lines):
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))


def read_tagged(file_path, tag):
    """The body of the tagged block, or None when the file has no such block."""
    parts = _split_tagged(_read_lines(file_path), tag)
    return None if parts is None else "\n".join(parts[1])


def sync_tagged(file_path, tag, body):
    """Make the tagged block hold `body`. Returns created, updated or unchanged.

    Replaces in place, so a repeat run rewrites nothing. Text outside the
    markers is never touched.
    """
    if not file_path or not tag:
        raise ValueError("no file or tag given")
    begin, end = _tag_markers(tag)
    want = body.strip("\n").split("\n")
    lines = _read_lines(file_path)
    parts = _split_tagged(lines, tag)
    if parts is None:
        out = list(lines)
        if out and out[-1].strip():
            out.append("")
        out += [begin] + want + [end]
        _write_lines(file_path, out)
        return "created"
    before, current, after = parts
    if current == want:
        return "unchanged"
    _write_lines(file_path, before + [begin] + want + [end] + after)
    return "updated"


def remove_tagged(file_path, tag):
    """Drop the tagged block and the blank line before it. True when removed."""
    lines = _read_lines(file_path)
    parts = _split_tagged(lines, tag)
    if parts is None:
        return False
    before, _, after = parts
    if before and not before[-1].strip():
        before = before[:-1]
    _write_lines(file_path, before + after)
    return True


if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    target = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        if action == "install":
            install(target)
        elif action == "remove":
            remove(target)
        else:
            print("usage: np-instruction-block.sh {install|remove} <file>", file=sys.stderr)
            sys.exit(2)
    except ValueError as exc:
        print("np-instruction-block: %s" % exc, file=sys.stderr)
        sys.exit(2)
