#!/usr/bin/env python3
"""nervepack critical-path checker (stdlib only, read-only).

Scan Markdown docs and skills for references to nervepack's setup/ and onboard/
assets and flag two failure modes that break a fresh install:

  STALE    a `setup/...` or `onboard/...` reference missing the `engine/` prefix.
           The engine/content split moved these under engine/, so the bare path
           is dead (this is the exact regression this guard exists to prevent).
  MISSING  an `engine/setup/<f>` / `engine/onboard/<f>` reference whose target
           file exists under none of the scanned roots or the engine root
           (a typo, or a rename that left a doc pointing at nothing).

Usage:  np-path-check.py [ROOT ...]
        Default ROOT is the engine repo root inferred from this script's location.
        Pass extra roots (e.g. your content overlay) to check their docs too;
        existence resolves against every root plus the engine root, so a doc in
        one repo may legitimately reference a script in another.

Exit 0 when every reference is well-formed and resolvable, 1 on any violation
(each printed as `<file>:<line>: <RULE>: <token>`), 2 on a usage error.
"""
import os
import re
import sys

# Directories whose Markdown is historical, auto-generated, or an intentional
# test fixture. Their path strings describe the past (or plant bad paths on
# purpose), so they must never be flagged.
SKIP_SEGMENTS = {".git", ".superpowers", "node_modules", "tests", "archive"}
SKIP_SUBPATHS = (
    os.path.join("docs", "superpowers", "plans"),
    os.path.join("docs", "superpowers", "specs"),
    os.path.join("docs", "superpowers", "runbooks"),
    "specs",   # engine-root design specs reference planned (not yet implemented) paths
    os.path.join("memory", "episodic"),
    os.path.join("memory", "playbooks"),
    os.path.join("memory", "strategies"),
)
# Append-only / narrative records — their path strings are a historical account,
# not live instructions, so a stale reference there is a record, not a bug.
SKIP_FILES = {"log.md"}

# A setup/onboard token and the path segment(s) after it.
_SEG = r"[\w.*<>{}\[\]-]+"
TOKEN = re.compile(r"(?<![A-Za-z0-9_-])(setup|onboard)/(" + _SEG + r"(?:/" + _SEG + r")*)")
ASSET_EXT = (".sh", ".py", ".conf", ".json", ".md", ".txt")
# Build placeholders (globs, <name>, NN-name, 5x-install) — a real reference but
# not a concrete file, so classify by prefix yet skip the existence check.
PLACEHOLDER = re.compile(r"[*<>{}\[\]]|(?:^|[/-])(?:NN|\dx)(?=[/-]|$)")


def is_asset(tail):
    """True when the token points at a file/dir, not prose like 'setup/teardown'."""
    return tail.endswith(ASSET_EXT) or "/" in tail or bool(PLACEHOLDER.search(tail))


def resolvable(sub, tail, roots):
    if PLACEHOLDER.search(tail):
        return True  # can't resolve a glob/placeholder — don't flag it
    return any(os.path.exists(os.path.join(r, "engine", sub, tail)) for r in roots)


def scan_file(path, relbase, res_roots, out):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return
    rel = os.path.relpath(path, relbase)
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in TOKEN.finditer(line):
            sub, tail = m.group(1), m.group(2)
            if not is_asset(tail):
                continue
            before = line[: m.start()]
            if before.endswith("engine/"):
                # A correct top-level reference — verify the target exists.
                if not resolvable(sub, tail, res_roots):
                    out.append(f"{rel}:{lineno}: MISSING: engine/{sub}/{tail}")
            elif before.endswith("nervepack/") or not (before and before[-1] == "/"):
                # Stale top-level: qualified `…/nervepack/setup/x` or a bare
                # `setup/x` (start of line or after a delimiter). Missing engine/.
                out.append(f"{rel}:{lineno}: STALE: {sub}/{tail} (should be engine/{sub}/{tail})")
            # else: preceded by another `dir/` (e.g. tests/onboard) — a subdir of
            # that name, not the top-level engine dir. Not our concern.


def should_skip(path, root):
    if os.path.basename(path) in SKIP_FILES:
        return True
    rel = os.path.relpath(path, root)
    if set(rel.split(os.sep)) & SKIP_SEGMENTS:
        return True
    return any(sub in rel for sub in SKIP_SUBPATHS)


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    engine_root = os.path.abspath(os.path.join(here, "..", ".."))
    roots = [os.path.abspath(a) for a in argv] or [engine_root]
    res_roots = list(dict.fromkeys(roots + [engine_root]))
    out = []
    for root in roots:
        if not os.path.isdir(root):
            print(f"np-path-check: not a directory: {root}", file=sys.stderr)
            return 2
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_SEGMENTS]
            for fn in filenames:
                if fn.endswith(".md"):
                    p = os.path.join(dirpath, fn)
                    if not should_skip(p, root):
                        scan_file(p, root, res_roots, out)
    for line in out:
        print(line)
    if out:
        print(f"\nnp-path-check: {len(out)} stale/broken path reference(s) found", file=sys.stderr)
        return 1
    print("np-path-check: all setup/onboard path references resolve ✓", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
