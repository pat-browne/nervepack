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
