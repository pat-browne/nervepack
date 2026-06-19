#!/usr/bin/env python3
"""nervepack publish scanner — block secrets/PII before publication.

Usage: np-publish-scan.py <staged-dir>
Exit 0 if clean, 1 if any non-allowlisted finding, 2 on usage error.
Pure stdlib. A finding is suppressed only if its (relpath, exact-matched-text)
appears in publish/scan-allowlist.txt (printed in the report so it can't grow silently).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWLIST = os.path.join(HERE, "scan-allowlist.txt")

RULES = {
    "aws-akia":    re.compile(r"AKIA[0-9A-Z]{16}"),
    "gh-token":    re.compile(r"gh[opsu]_[A-Za-z0-9]{20,}"),
    "openai-sk":   re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "pii-email":   re.compile(r"pmb21656|[A-Za-z0-9._%+-]+@gmail\.com"),
    "pii-user":    re.compile(r"/home/pbrowne|patrick\.browne"),
    # pat-browne is the PUBLIC repo owner (project identity), intentionally NOT flagged —
    # see docs/superpowers/specs/2026-06-10-nervepack-genericization-design.md §5.
    "pii-handle":  re.compile(r"pbrowne\.net"),
    # RFC1918 private LAN addresses (a real home/office box) are infra residue that
    # must not ship publicly. Matches 10/8, 172.16/12, and 192.168/16 only — never
    # loopback (127.0.0.1), 0.0.0.0, the 172.16–31 boundary neighbors, TEST-NET doc
    # ranges, or public IPs. The dashboard's intentional 127.0.0.1 binds stay clean.
    "lan-ip":      re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b"),
}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".claude"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".zip", ".lock"}
# The scanner's own machinery: this source file holds the detection regexes
# (e.g. the pii- patterns) and the scanner's unit tests plant fake-but-real-looking
# secrets/PII to prove the rules fire. Scanning them would flag the guard against
# itself. They are reviewed, tiny, and never carry genuine leaked data, so skip
# them by exact relpath (everything else, including all engine code/docs, is scanned).
SKIP_FILES = {
    "publish/np-publish-scan.py",
    "publish/scan-allowlist.txt",
    "engine/setup/tests/publish/test_scan.py",
    "engine/setup/tests/publish/test_no_engine_pii.py",
    "engine/setup/tests/publish/test_snapshot.sh",  # plants a fake AKIA + LAN IP to prove the gate blocks
}


def load_allowlist(path):
    allow = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#") or "\t" not in line:
                    continue
                rel, txt = line.split("\t", 1)
                allow.add((rel, txt))
    return allow


def scan(root, allow):
    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_DIRS:  # e.g. a git-worktree `.git` pointer FILE (never publishable)
                continue
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if rel in SKIP_FILES:
                continue
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for rule, rx in RULES.items():
                            for m in rx.findall(line):
                                txt = m if isinstance(m, str) else m[0]
                                if (rel, txt) in allow:
                                    continue
                                findings.append((rel, lineno, rule, txt))
            except OSError:
                continue
    return findings


def main(argv):
    if len(argv) < 2:
        print("usage: np-publish-scan.py <staged-dir>", file=sys.stderr)
        return 2
    allow = load_allowlist(ALLOWLIST)
    findings = scan(argv[1], allow)
    if allow:
        print(f"[scan] {len(allow)} allowlisted false-positive(s) in effect:")
        for rel, txt in sorted(allow):
            print(f"    ALLOW {rel} :: {txt[:48]}")
    if findings:
        print(f"[scan] BLOCKED — {len(findings)} finding(s):", file=sys.stderr)
        for rel, lineno, rule, txt in findings:
            print(f"    {rel}:{lineno} [{rule}] {txt[:48]}", file=sys.stderr)
        return 1
    print("[scan] clean — no secrets/PII found.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
