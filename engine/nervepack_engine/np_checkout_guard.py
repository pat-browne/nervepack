"""Stale-checkout guard: is each knowledge checkout on main and current?

Sessions read wiki/skills from the WORKING TREE of the engine and the content
overlay(s). Another session may leave one of those on a feature branch or far
behind origin/main, and the reader then trusts stale notes. This module reports,
per checkout, the branch, commits behind origin/main, and dirty state.

SessionStart uses the last-fetched origin/main ref only (no network); the doctor
may pass fetch=True to refresh it first. Every git failure degrades to "unknown",
never an exception.
"""
import os
import subprocess

import np_content

_BASE = "origin/main"


def _git(repo, *args, timeout=20):
    try:
        r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def check(repo, fetch=False):
    """Return a dict for one checkout, or None when it is not a git repo."""
    if not repo or _git(repo, "rev-parse", "--git-dir") is None:
        return None
    if fetch:
        _git(repo, "fetch", "--quiet", "origin", "main", timeout=30)
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "?"
    behind = _git(repo, "rev-list", "--count", "HEAD.." + _BASE)
    dirty = _git(repo, "status", "--porcelain")
    return {
        "repo": repo,
        "branch": branch,
        "behind": int(behind) if behind and behind.isdigit() else None,
        "dirty": bool(dirty),
    }


def problems(info):
    """Human-readable reasons this checkout is unsafe to read, [] when fine."""
    out = []
    if info["branch"] != "main":
        out.append("on branch %s, not main" % info["branch"])
    if info["behind"]:
        out.append("%d commit(s) behind %s" % (info["behind"], _BASE))
    return out


def checkouts():
    """Engine plus each resolved overlay (personal, then team), deduped."""
    engine = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    repos = [engine]
    try:
        repos += list(reversed(np_content.content_layers()))
    except Exception:
        pass
    seen, out = set(), []
    for r in repos:
        real = os.path.realpath(r)
        if real not in seen:
            seen.add(real)
            out.append(r)
    return out


def scan(fetch=False, repos=None):
    return [i for i in (check(r, fetch) for r in (repos or checkouts())) if i]


def warning(infos):
    """Loud multi-line warning for the agent, "" when every checkout is fine."""
    bad = [(i, problems(i)) for i in infos if problems(i)]
    if not bad:
        return ""
    lines = ["NERVEPACK WARNING: stale knowledge checkout. Working-tree reads of wiki, "
             "skills and memory may be OUTDATED."]
    for i, ps in bad:
        lines.append("- %s: %s%s" % (i["repo"], "; ".join(ps),
                                     " (dirty)" if i["dirty"] else ""))
    lines.append("Do NOT trust those working trees. Read knowledge with "
                 "`git -C <repo> show origin/main:<path>`, or sync first "
                 "(`git -C <repo> checkout main && git -C <repo> pull --ff-only`).")
    return "\n".join(lines)


def doctor_status(fetch=True):
    infos = scan(fetch=fetch)
    bad = [(i, problems(i)) for i in infos if problems(i)]
    if not bad:
        return "PASS (%d checkout(s) on main and current)" % len(infos)
    return "WARN (%s -- read via `git -C <repo> show origin/main:<path>` or sync)" % "; ".join(
        "%s: %s" % (i["repo"], ", ".join(ps)) for i, ps in bad)
