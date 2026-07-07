#!/usr/bin/env python3
"""Engine-layout guard: fail if any git-tracked file sits at an overlay-only doc path.

Design specs, plans, and runbooks (superpowers brainstorm output) are *content*, not
engine — they belong in ``$NP_CONTENT_DIR/docs/superpowers/{specs,plans,runbooks}/``,
never in this repo (see AGENTS.md, "Directory contract"). A spec committed to the engine
also drags its forward-references (files it plans but hasn't built) past np-path-check.
This deterministic check (no LLM) runs in the regression suite so such a file cannot be
committed to the engine again.

Usage:  np-engine-layout-check.py [repo_root]      # default: current directory
Exit 0 = clean; 1 = one or more overlay-only docs are tracked in the engine.
"""
import os
import re
import subprocess
import sys

# Overlay-only path prefixes that must never appear in the engine tree.
# Anchored at the repo root: a nested `.../specs/` (e.g. a test fixture) is fine.
FORBIDDEN = re.compile(r"^(specs|plans|runbooks)/|^docs/superpowers/")


def tracked_files(root):
    """Git-tracked paths (committed/staged), repo-root-relative. Not the working tree,
    so untracked scratch never false-positives (see np-kb-testing-ci §7)."""
    out = subprocess.run(
        ["git", "-C", root, "ls-files"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.splitlines()


def scan_paths(paths):
    """Pure: the subset of paths that sit at an overlay-only location."""
    return [p for p in paths if FORBIDDEN.match(p)]


def main(argv):
    root = argv[1] if len(argv) > 1 else os.getcwd()
    bad = scan_paths(tracked_files(root))
    if bad:
        sys.stderr.write(
            "engine-layout-check: %d overlay-only doc(s) tracked in the engine "
            "(move to $NP_CONTENT_DIR/docs/superpowers/{specs,plans,runbooks}/ — see "
            "AGENTS.md 'Directory contract'):\n" % len(bad)
        )
        for p in sorted(bad):
            sys.stderr.write("  " + p + "\n")
        return 1
    print("engine-layout-check: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
