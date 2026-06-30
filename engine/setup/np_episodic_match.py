"""Pure-Python port of episodic-match.sh — keyword-match a prompt against an
INDEX.md table, returning matching topic cells, highest score first.

Parity-locked to the bash original by tests/mcp/parity/test_episodic_match_parity.sh
(byte-identical stdout across a fixture table). The long-running MCP server calls
match() in-process for nervepack_recall so it needs no bash; the bash script stays
the source of truth for the hot-path recall hooks. stdlib only. Slice 3 of the
git-for-windows-free MCP work (#38).

Faithful to the bash semantics, quirks included:
- prompt normalized: lowercase, non-alnum runs -> single space, space-padded.
- keywords split on comma/whitespace only (so a hyphenated keyword like
  `wyoming-tts` keeps its hyphen and therefore never matches a prompt, whose
  hyphens became spaces — same as the awk original).
- whole-word match via the space-padded prompt; score = number of matching keywords.
- output order mirrors `sort -rn | cut -f2`: score desc, ties by the full
  "score\\ttopic" line desc.
"""
import os
import re
import sys


def _normalize_prompt(text):
    # Mirror: tr '[:upper:]' '[:lower:]' | tr -cs '[:alnum:]' ' ', then space-pad.
    return " " + re.sub(r'[^a-z0-9]+', ' ', text.lower()) + " "


def match(index_path, prompt):
    """Return the matching topic cells, highest score first (bash-identical order).
    Missing/empty index -> [] (the bash script exits 0 with no output)."""
    if not os.path.isfile(index_path):
        return []
    norm = _normalize_prompt(prompt)
    rows = []  # (score, topic, sort_line)
    with open(index_path, "r", encoding="utf-8", newline="") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not re.match(r'^[ \t\r\v\f]*\|', line):
                continue
            if re.search(r'topic[ \t\r\v\f]*\|[ \t\r\v\f]*last_updated', line):
                continue  # header row
            if re.match(r'^[ \t\r\v\f]*\|[-:\s|]+$', line):
                continue  # separator row
            fields = line.split("|")
            topic = fields[1].strip() if len(fields) > 1 else ""
            kw = fields[3].strip() if len(fields) > 3 else ""
            if topic == "":
                continue
            score = 0
            for tok in re.split(r'[,\s]+', kw):
                k = tok.lower()
                if k and (" " + k + " ") in norm:
                    score += 1
            if score > 0:
                rows.append((score, topic, "%d\t%s" % (score, topic)))
    # `sort -rn | cut -f2`: numeric score desc, ties broken by the full line desc.
    rows.sort(key=lambda r: (r[0], r[2]), reverse=True)
    return [r[1] for r in rows]


if __name__ == "__main__":
    # CLI mirror of episodic-match.sh: argv[1]=INDEX.md, prompt on stdin, topics on stdout.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")   # emit LF (Windows text-mode would give CRLF)
    if len(sys.argv) < 2:
        sys.stderr.write("usage: np_episodic_match.py <INDEX.md>  (prompt on stdin)\n")
        sys.exit(2)
    for topic in match(sys.argv[1], sys.stdin.read()):
        sys.stdout.write(topic + "\n")
