"""Bash-free byte-exact port of episodic-scrub.sh — redact secret-shaped
substrings from stdin -> stdout. Defense-in-depth before an episodic note is
written to the inbox; conservative (known token shapes), fail-open.

Parity-locked to episodic-scrub.sh by tests/mcp/parity/test_scrub_parity.sh
(byte-identical output). Operates on BYTES, per line (like sed under LC_ALL=C),
so it never chokes on invalid-UTF-8 input. stdlib only. Used by the ported
capture pipeline (np_capture) on a bash-free host. Slice 4 of #38.

When NP_PII_FILTER=1, also applies structural PII regex rules (email, phone,
SSN, private IP, path, token) matching np-pii-filter.py --mode fast patterns.
"""
import os
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

# Structural PII rules (email, phone, SSN, private IP, path, token) — applied only
# when NP_PII_FILTER=1. Matches np-pii-filter.py --mode fast patterns exactly.
_PII_RULES = [
    (re.compile(rb"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"), b"[EMAIL]"),
    (re.compile(rb"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}"), b"[PHONE]"),
    (re.compile(rb"\d{3}-\d{2}-\d{4}"), b"[SSN]"),
    (re.compile(
        rb"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        rb"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        rb"|192\.168\.\d{1,3}\.\d{1,3})"
    ), b"[IP]"),
    (re.compile(rb"/(?:home|Users)/[A-Za-z][A-Za-z0-9_\-]*/"), b"[PATH]/"),
    (re.compile(rb"sk-[A-Za-z0-9]{16,}"), b"[TOKEN]"),
    (re.compile(rb"gh[opusr]_[A-Za-z0-9]{20,}"), b"[TOKEN]"),
    (re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"), b"[TOKEN]"),
    (re.compile(rb"AKIA[0-9A-Z]{16}"), b"[TOKEN]"),
    (re.compile(rb"xox[baprs]-[A-Za-z0-9\-]{10,}"), b"[TOKEN]"),
    (re.compile(rb"[Bb]earer\s+[A-Za-z0-9._\-]{12,}"), b"Bearer [TOKEN]"),
]


def scrub_line(line: bytes) -> bytes:
    for pat, repl in _COMPILED:
        line = pat.sub(repl, line)
    if os.environ.get("NP_PII_FILTER") == "1":
        for pat, repl in _PII_RULES:
            line = pat.sub(repl, line)
    return line


def scrub(data: bytes) -> bytes:
    """Redact `data` (bytes) per line; preserves the exact newline structure."""
    return b"\n".join(scrub_line(seg) for seg in data.split(b"\n"))


def main() -> None:
    sys.stdout.buffer.write(scrub(sys.stdin.buffer.read()))


if __name__ == "__main__":
    main()
