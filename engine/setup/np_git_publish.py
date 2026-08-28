"""Publish a cron's local commit to origin/main, loudly.

Every scheduled writer used to do this instead:

    subprocess.run(["git", "-C", repo, "push", "-q", "origin", "HEAD:main"],
                   stdout=DEVNULL, stderr=DEVNULL, check=False)

Two faults compound there. The push names HEAD without checking that HEAD is
main, and the result is discarded. Park the checkout on a feature branch and
every push becomes a rejected non-fast-forward, while the job still exits 0.
Observed 2026-08-28 on nervepack-content: 33 cron commits accumulated over two
days on a branch 198 behind main, and no log line said so.

This module refuses to guess. When HEAD is not main it declines and says why,
leaving the commit safe in the local branch. When the push itself fails it
returns git's stderr rather than swallowing it.
"""

import subprocess


_MAX_DETAIL = 300


def _one_line(text, limit=_MAX_DETAIL):
    """Collapse git's stderr to one bounded line.

    A push rejection is routinely multi-line, and these strings land in a
    caller's status line and in a cron log. Left raw they turn one event into
    several log lines that no longer parse as one record.
    """
    if not text:
        return ""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit - 3] + "..."


def current_branch(repo):
    """Branch name at HEAD, or None when detached or not a repo."""
    try:
        r = subprocess.run(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    name = r.stdout.strip()
    return None if name in ("", "HEAD") else name


def push_to_main(repo, branch="main"):
    """Push HEAD to origin/<branch>, but only when HEAD IS that branch.

    Returns (ok, detail). `detail` is empty on success and carries the reason
    on refusal or failure, so the caller can put it in its status line.
    Never raises: a scheduled job must not die here.
    """
    head = current_branch(repo)
    if head is None:
        return False, "refused: %s has a detached HEAD or is not a git repo" % repo
    if head != branch:
        return False, ("refused: %s is on '%s', not '%s'. The commit is safe locally. "
                       "Return the checkout to '%s' so it can publish."
                       % (repo, head, branch, branch))
    try:
        r = subprocess.run(["git", "-C", repo, "push", "-q", "origin",
                            "HEAD:%s" % branch],
                           capture_output=True, text=True)
    except OSError as exc:
        return False, "push failed: %s" % exc
    if r.returncode != 0:
        # Always carry the exit status, and add git's own words when it gave any.
        # `push rejected: returncode 1` alone tells an operator nothing, and a
        # quiet failure is the exact class of fault this module exists to end.
        detail = "exit %d" % r.returncode
        err = _one_line(r.stderr)
        if err:
            detail += ": %s" % err
        return False, "push rejected (%s)" % detail
    return True, ""
