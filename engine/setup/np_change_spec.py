#!/usr/bin/env python3
"""Change-spec resolution and blast-radius matching, shared by both gates.

`np-spec-guard.py` (the CI job, F2/#248) and `hooks/drift_guard.py` (the
PreToolUse hook, F3/#249) enforce the same policy at two different moments. If
they carried separate copies of the matcher, a branch could pass locally and
fail CI on the radius alone -- and the local gate would be teaching the session
a rule CI does not actually hold. One matcher, two callers.

`fnmatch`'s `*` is NOT path-aware -- it translates to regex `.*` and already
crosses `/` -- so a single `*` behaves like a recursive glob here. Patterns are
written assuming any wildcard reaches arbitrary depth. This is inherited
deliberately from np-spec-guard.py rather than "fixed": changing it would
silently reinterpret every blast_radius already committed.

Pure stdlib.
"""
import fnmatch
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import np_frontmatter  # noqa: E402

SPEC_DIR = "change-specs"


def branch_slug(branch):
    """Git branch name -> the spec's filename stem (`feat/x` -> `feat-x`)."""
    return branch.replace("/", "-")


def spec_rel_for(slug):
    """Repo-relative path of the spec for `slug`, forward-slashed."""
    return "%s/%s.md" % (SPEC_DIR, slug)


def spec_path_for(root, slug):
    """Absolute path of the spec for `slug` under repo `root`."""
    return os.path.join(root, SPEC_DIR, "%s.md" % slug)


def outside_radius(files, globs):
    """The subset of `files` that no glob in `globs` admits.

    Empty `globs` puts everything outside: a spec that declares no radius has
    granted no permission. Callers decide what to DO about that -- spec-guard
    fails the PR, drift_guard warns rather than denying every edit in the repo.
    """
    if not globs:
        return list(files)
    return [f for f in files if not any(fnmatch.fnmatch(f, g) for g in globs)]


def in_radius(rel, globs):
    """True when repo-relative path `rel` is admitted by `globs`."""
    return not outside_radius([rel], globs)


def repo_root(start):
    """Nearest ancestor of `start` containing a `.git`, or "" when there is none.

    Walks up rather than requiring `start` to exist: a Write routinely names a
    file, and sometimes a directory, that is not on disk yet.
    """
    try:
        path = os.path.realpath(start)
    except OSError:
        return ""
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return ""
        path = parent


def _git_dir(root):
    """The real gitdir for `root`. A linked worktree's `.git` is a FILE holding
    `gitdir: <path>`; reading it as a directory is how a worktree loses its
    branch and silently escapes the guard."""
    git = os.path.join(root, ".git")
    if os.path.isdir(git):
        return git
    try:
        with open(git, encoding="utf-8", errors="replace") as fh:
            line = fh.readline().strip()
    except OSError:
        return ""
    if not line.startswith("gitdir:"):
        return ""
    target = line[len("gitdir:"):].strip()
    if not os.path.isabs(target):
        target = os.path.join(root, target)
    return os.path.normpath(target)


def current_branch(root):
    """Checked-out branch name, or "" when detached, unreadable, or absent.

    Reads `HEAD` directly instead of shelling to `git rev-parse`. drift_guard
    runs on every Write and Edit, where a subprocess costs 10-20ms and buys
    nothing this file read does not already give.
    """
    git = _git_dir(root)
    if not git:
        return ""
    try:
        with open(os.path.join(git, "HEAD"), encoding="utf-8",
                  errors="replace") as fh:
            head = fh.readline().strip()
    except OSError:
        return ""
    if not head.startswith("ref:"):
        return ""  # detached HEAD -- a raw sha, no branch, so no spec to find
    ref = head[len("ref:"):].strip()
    prefix = "refs/heads/"
    return ref[len(prefix):] if ref.startswith(prefix) else ""


def load(root, branch):
    """(spec_rel, globs) for `branch` in `root`.

    `("", [])` means no spec exists -- the repo has not adopted the convention.
    `("change-specs/x.md", [])` means a spec exists but declares no radius,
    which is a different situation and a different caller response.
    """
    slug = branch_slug(branch)
    path = spec_path_for(root, slug)
    if not os.path.isfile(path):
        return ("", [])
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ("", [])
    return (spec_rel_for(slug), np_frontmatter.list_field(text, "blast_radius"))
