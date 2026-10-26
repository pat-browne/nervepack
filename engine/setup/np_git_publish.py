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

The commit still landed off main, and 114 piled up by 2026-10-26. So
write_root() now sends a deterministic cron to a private worktree at
origin/main when the checkout is elsewhere. Agentic crons refuse instead.
"""

import hashlib
import os
import shutil
import subprocess
import sys


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


def _git(repo, *args):
    """git -C <repo>. Returns (rc, stdout, stderr). Never raises."""
    try:
        r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
    except OSError as exc:
        return 1, "", str(exc)
    return r.returncode, r.stdout.strip(), r.stderr


def _ref_exists(repo, ref):
    return _git(repo, "rev-parse", "-q", "--verify", ref + "^{commit}")[0] == 0


def off_main(repo, branch="main"):
    """What HEAD is on when it is not <branch>, else None.

    A repo with no <branch> at all has no trunk to protect, so it reads None.
    """
    if _git(repo, "rev-parse", "--git-dir")[0] != 0:
        return None
    if not (_ref_exists(repo, "refs/heads/" + branch)
            or _ref_exists(repo, "refs/remotes/origin/" + branch)):
        return None
    head = current_branch(repo)
    if head == branch:
        return None
    return head or "detached HEAD"


def off_main_message(job, repo, head, branch="main"):
    return ("%s: %s is on '%s', not '%s'. The scheduled writer will not commit "
            "there." % (job, repo, head, branch))


def worktree_root():
    override = os.environ.get("NP_CRON_WORKTREES")
    if override:
        return override
    import np_dirs  # callers put engine/nervepack_engine on sys.path
    return np_dirs.cache_path("cron-worktrees")


def _is_cron_worktree(path):
    root = os.path.realpath(worktree_root())
    return os.path.realpath(path).startswith(root + os.sep)


def cron_worktree(repo, branch="main"):
    """Create or reuse a detached worktree of <repo> at origin/<branch>.

    Returns (path, "") or (None, why). Never raises.
    """
    rc, top, _ = _git(repo, "rev-parse", "--show-toplevel")
    if rc != 0 or not top:
        return None, "not a git repo: %s" % repo
    tag = hashlib.sha1(os.path.realpath(top).encode("utf-8")).hexdigest()[:8]
    wt = os.path.join(worktree_root(), "%s-%s" % (os.path.basename(top), tag))

    _git(top, "fetch", "-q", "origin", branch)  # offline: use the last-known ref
    base = "origin/" + branch
    if not _ref_exists(top, "refs/remotes/" + base):
        base = branch

    if not (os.path.isfile(os.path.join(wt, ".git"))
            and _git(wt, "rev-parse", "--git-dir")[0] == 0):
        # Missing or broken. The dir is ours, so clear it and add it again.
        if os.path.exists(wt):
            shutil.rmtree(wt, ignore_errors=True)
        _git(top, "worktree", "prune")
        try:
            os.makedirs(os.path.dirname(wt), exist_ok=True)
        except OSError as exc:
            return None, "cannot create %s: %s" % (wt, exc)
        rc, _, err = _git(top, "worktree", "add", "-q", "--detach", wt, base)
        if rc != 0:
            return None, "worktree add failed: %s" % _one_line(err)
        return wt, ""

    # Reused. Drop crash leftovers. Rebase any commit a failed push left behind.
    _git(wt, "reset", "-q", "--hard")
    _git(wt, "clean", "-fdq")
    if _git(wt, "merge", "-q", "--ff-only", base)[0] != 0:
        rc, _, err = _git(wt, "rebase", "-q", base)
        if rc != 0:
            _git(wt, "rebase", "--abort")
            return None, "cron worktree %s cannot reach %s: %s" % (
                wt, base, _one_line(err))
    return wt, ""


def write_root(repo, job, branch="main"):
    """Where a deterministic cron writes and commits: (path, note).

    The repo on <branch>, else the cron worktree. path is None when neither is safe.
    """
    try:
        head = off_main(repo, branch)
        if head is None:
            return repo, ""
        msg = off_main_message(job, repo, head, branch)
        wt, why = cron_worktree(repo, branch)
        if wt is None:
            print("%s Refusing: %s" % (msg, why), file=sys.stderr)
            return None, "off-main (%s): %s" % (head, why)
        print("%s Writing in cron worktree %s." % (msg, wt), file=sys.stderr)
        return wt, "off-main (%s), wrote via cron worktree" % head
    except Exception as exc:  # fail-open: never crash a cron
        return None, "write_root error: %s" % exc


def publish(path, branch="main"):
    """Push from a live checkout (branch-guarded) or from a cron worktree."""
    if _is_cron_worktree(path):
        return _push(path, branch)
    return push_to_main(path, branch)


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
    return _push(repo, branch)


def _push(repo, branch):
    try:
        r = subprocess.run(["git", "-C", repo, "push", "-q", "origin",
                            "HEAD:refs/heads/%s" % branch],
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
