"""Bash-free byte-exact port of episodic-scrub.sh — redact secret-shaped
substrings from stdin -> stdout. Defense-in-depth before an episodic note is
written to the inbox; conservative (known token shapes), fail-open.

Parity-locked to episodic-scrub.sh by tests/mcp/parity/test_scrub_parity.sh
(byte-identical output). Operates on BYTES, per line (like sed under LC_ALL=C),
so it never chokes on invalid-UTF-8 input. stdlib only. Used by the ported
capture pipeline (np_capture) on a bash-free host. Slice 4 of #38.
"""
import re
import sys

# The sed -E rules, in order. \s in a bytes pattern is exactly POSIX [[:space:]]
# under LC_ALL=C ([ \t\n\r\f\v]); processing per-line means \n never appears within
# a segment, matching sed's line-at-a-time behavior.
_RULES = [
    (rb'sk-[A-Za-z0-9]{16,}', rb'[REDACTED-SECRET]'),
    (rb'github_pat_[A-Za-z0-9_]{20,}', rb'[REDACTED-SECRET]'),
    (rb'gh[opusr]_[A-Za-z0-9]{20,}', rb'[REDACTED-SECRET]'),
    (rb'AKIA[0-9A-Z]{16}', rb'[REDACTED-SECRET]'),
    (rb'xox[baprs]-[A-Za-z0-9-]{10,}', rb'[REDACTED-SECRET]'),
    (rb'(aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*[A-Za-z0-9/+]{40}',
     rb'\1=[REDACTED-SECRET]'),
    (rb'[Bb]earer\s+[A-Za-z0-9._-]{12,}', rb'Bearer [REDACTED-SECRET]'),
    (rb'([Pp]assword|[Pp]asswd|[Ss]ecret|[Tt]oken|[Aa]pi[_-]?[Kk]ey)("?\s*[:=]\s*"?)[^\s"]{6,}',
     rb'\1\2[REDACTED-SECRET]'),
    (rb'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}', rb'[REDACTED-JWT]'),
    (rb'-----BEGIN[ A-Z]*PRIVATE KEY-----', rb'[REDACTED-KEY]'),
]
_COMPILED = [(re.compile(p), r) for p, r in _RULES]


def scrub_line(line):
    for pat, repl in _COMPILED:
        line = pat.sub(repl, line)
    return line


def scrub(data):
    """Redact `data` (bytes) per line; preserves the exact newline structure."""
    return b"\n".join(scrub_line(seg) for seg in data.split(b"\n"))


def main():
    sys.stdout.buffer.write(scrub(sys.stdin.buffer.read()))


if __name__ == "__main__":
    main()
