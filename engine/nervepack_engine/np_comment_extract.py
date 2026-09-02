"""Conservative, per-language comment extraction for form_gate's comment-lint
feature (change-specs/feat-form-gate-comment-lint.md).

Pure stdlib, line-oriented -- no third-party parser. Deliberately
under-extracts: when a case is ambiguous (a triple-quoted string that might
not be a docstring, a `#` that might sit inside a string literal), it is
skipped rather than risking a false positive that lints code or string-literal
data as prose. Fail-safe throughout: on any parse difficulty, return whatever
has been extracted so far. Never raise.
"""
import re

_C_LIKE_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs",
               ".java", ".c", ".h", ".cpp", ".cc")
_SHELL_EXT = (".sh", ".bash", ".zsh")
_SQL_EXT = (".sql",)

# A quoted string on a single physical line: "...", '...'. Used to blank out
# string content before searching for a comment marker, so a marker character
# sitting inside a string literal is never mistaken for a real one.
_STRIP_STRINGS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')

_PY_DEF_CLASS = re.compile(r"^\s*(?:async\s+def|def|class)\b.*:\s*$")
_PY_TRIPLE = re.compile(r'^[a-zA-Z]{0,2}(\'\'\'|""")')


def extract_comments(text, ext):
    """Return (comment_text, max_block_lines) for `text` of extension `ext`.

    comment_text is the concatenated comment/docstring prose worth linting
    (empty string if none was found). max_block_lines is the length of the
    longest contiguous comment block, for the length-ceiling rule. Never
    raises -- any parse difficulty just returns what was extracted so far.
    """
    try:
        ext = (ext or "").lower()
        text = text or ""
        if ext == ".py":
            return _extract_python(text)
        if ext in _C_LIKE_EXT:
            return _extract_c_like(text)
        if ext in _SHELL_EXT:
            return _extract_line_marker(text, "#")
        if ext in _SQL_EXT:
            return _extract_line_marker(text, "--")
        return ("", 0)
    except Exception:
        return ("", 0)


def _triple_quote_start(stripped):
    m = _PY_TRIPLE.match(stripped)
    return m.group(1) if m else None


def _consume_triple_quoted(lines, i, quote):
    """Return (last_line_index, docstring_text) for a triple-quoted string
    opening on lines[i]. Fails safe to end-of-file on an unterminated string
    rather than raising."""
    first = lines[i]
    start = first.find(quote)
    rest = first[start + 3:]
    end = rest.find(quote)
    if end != -1:
        return i, rest[:end]
    parts = [rest]
    j = i + 1
    while j < len(lines):
        line = lines[j]
        end = line.find(quote)
        if end != -1:
            parts.append(line[:end])
            return j, "\n".join(parts)
        parts.append(line)
        j += 1
    return len(lines) - 1, "\n".join(parts)


def _extract_python(text):
    lines = text.splitlines()
    chunks = []
    blocks = []
    run = [0]

    def flush_run():
        if run[0]:
            blocks.append(run[0])
            run[0] = 0

    prev_meaningful = ""
    seen_any_statement = False
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_run()
            i += 1
            continue
        if stripped.startswith("#"):
            comment = stripped[1:].strip()
            if comment:
                chunks.append(comment)
            run[0] += 1
            i += 1
            continue
        quote = _triple_quote_start(stripped)
        if quote and (not seen_any_statement or _PY_DEF_CLASS.match(prev_meaningful)):
            flush_run()
            end_i, doc_text = _consume_triple_quoted(lines, i, quote)
            if doc_text.strip():
                chunks.append(doc_text)
            blocks.append(end_i - i + 1)
            seen_any_statement = True
            prev_meaningful = stripped
            i = end_i + 1
            continue
        # An ordinary code line. Flush any run in progress, then check for a
        # trailing `#` comment -- only outside string literals.
        flush_run()
        scan = _STRIP_STRINGS.sub(lambda m: " " * len(m.group(0)), line)
        idx = scan.find("#")
        if idx != -1:
            trailing = line[idx + 1:].strip()
            if trailing:
                chunks.append(trailing)
            blocks.append(1)
        seen_any_statement = True
        prev_meaningful = stripped
        i += 1
    flush_run()
    return ("\n".join(c for c in chunks if c.strip()),
            max(blocks) if blocks else 0)


def _find_c_comment_start(line):
    """Return ('line'|'block', index) for the first non-string, non-URL
    comment start in `line`, or (None, -1). A quote character (single,
    double, or backtick for template literals) opens a string that swallows
    everything until its match; `https://` is skipped explicitly so a bare
    URL is never mistaken for a `//` line comment."""
    in_str = None
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "\"'`":
            in_str = c
            i += 1
            continue
        if line[i:i + 2] == "//":
            prefix = line[max(0, i - 6):i]
            if prefix.endswith("http:") or prefix.endswith("https:"):
                i += 2
                continue
            return ("line", i)
        if line[i:i + 2] == "/*":
            return ("block", i)
        i += 1
    return (None, -1)


def _extract_c_like(text):
    lines = text.splitlines()
    chunks = []
    blocks = []
    run = [0]
    in_block = [False]
    block_chunks = []
    block_start = [0]

    def flush_run():
        if run[0]:
            blocks.append(run[0])
            run[0] = 0

    for i, line in enumerate(lines):
        if in_block[0]:
            end = line.find("*/")
            if end != -1:
                block_chunks.append(line[:end])
                chunks.append("\n".join(block_chunks))
                blocks.append(i - block_start[0] + 1)
                in_block[0] = False
                block_chunks.clear()
            else:
                block_chunks.append(line)
            continue

        kind, idx = _find_c_comment_start(line)
        if kind == "line":
            code_before = line[:idx].strip()
            comment_text = line[idx + 2:].strip()
            if comment_text:
                chunks.append(comment_text)
            if code_before:
                flush_run()
                blocks.append(1)
            else:
                run[0] += 1
            continue

        flush_run()
        if kind == "block":
            after = line[idx + 2:]
            end = after.find("*/")
            if end != -1:
                if after[:end].strip():
                    chunks.append(after[:end])
                blocks.append(1)
            else:
                block_start[0] = i
                block_chunks = [after]
                in_block[0] = True
        # else: an ordinary code line, nothing to record.

    flush_run()
    if in_block[0] and block_chunks:
        chunks.append("\n".join(block_chunks))
        blocks.append(len(lines) - block_start[0])
    return ("\n".join(c for c in chunks if c.strip()),
            max(blocks) if blocks else 0)


def _extract_line_marker(text, marker):
    """Shell/SQL: a single line-comment marker (`#` or `--`), skipped when it
    falls inside a quoted string."""
    lines = text.splitlines()
    chunks = []
    blocks = []
    run = [0]

    def flush_run():
        if run[0]:
            blocks.append(run[0])
            run[0] = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_run()
            continue
        scan = _STRIP_STRINGS.sub(lambda m: " " * len(m.group(0)), line)
        idx = scan.find(marker)
        if idx == -1:
            flush_run()
            continue
        code_before = line[:idx].strip()
        comment_text = line[idx + len(marker):].strip()
        if comment_text:
            chunks.append(comment_text)
        if code_before:
            flush_run()
            blocks.append(1)
        else:
            run[0] += 1
    flush_run()
    return ("\n".join(c for c in chunks if c.strip()),
            max(blocks) if blocks else 0)
