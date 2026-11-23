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
import time


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
                           text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL)
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
    root = os.path.normcase(os.path.realpath(worktree_root()))
    return os.path.normcase(os.path.realpath(path)).startswith(root + os.sep)


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
            try:
                shutil.rmtree(wt)
            except OSError as exc:
                return None, "cannot clear broken cron worktree %s: %s" % (wt, exc)
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
            # Park the stranded commit on a ref and reset, so the cron never wedges.
            _git(wt, "rebase", "--abort")
            ref = "refs/nervepack/stranded/%d" % int(time.time())
            _git(wt, "update-ref", ref, "HEAD")
            _git(wt, "reset", "-q", "--hard", base)
            print("cron worktree %s could not rebase onto %s (%s). Saved the old "
                  "commit as %s." % (wt, base, _one_line(err), ref), file=sys.stderr)
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
    return sync_push(repo, branch)


def sync_push(repo, branch="main", regen=None):
    """Fetch, rebase unpushed commits onto origin/<branch>, then push.

    A conflict in a `*.jsonl` file is a union of both sides. A conflict in a
    generated file takes origin's copy, then `regen(repo)` rebuilds it and the
    result is committed. Any other conflict aborts the rebase and returns
    (False, why) with the local commits intact. Never force-pushes.
    Returns (ok, detail). Never raises.
    """
    regen = regen or rebuild_generated
    detail = ""
    for _ in range(2):  # a second pass covers a writer that pushes mid-sync
        ok, note = _sync(repo, branch, regen)
        if not ok:
            return ok, note
        ok, detail = _push_once(repo, branch)
        if ok:
            # On success the detail carries a fetch warning, so the cron logs it.
            return ok, note
        if not _is_behind(detail):
            return ok, "%s; %s" % (detail, note) if note else detail
    return False, detail


def _sync(repo, branch, regen):
    """Bring HEAD on top of origin/<branch>. (ok, why).

    A failed fetch is ok with a note: the push still runs and says the rest.
    """
    rc, _, err = _git(repo, "fetch", "-q", "origin", branch)
    if rc != 0:
        note = "fetch failed in %s: %s" % (repo, _one_line(err))
        print("np_git_publish: %s" % note, file=sys.stderr)
        return True, note
    base = "refs/remotes/origin/" + branch
    if _git(repo, "merge-base", "--is-ancestor", base, "HEAD")[0] == 0:
        return True, ""
    if not _clean(repo):
        return False, ("refused: %s is behind origin/%s and has uncommitted "
                       "changes, so it cannot rebase" % (repo, branch))
    ahead = _git(repo, "rev-list", "--count", base + "..HEAD")[1] or "0"
    rc, why, rebuilt = _rebase(repo, base)
    if rc != 0:
        msg = ("sync conflict (%s): rebase onto origin/%s aborted, %s commit(s) "
               "kept local in %s" % (why, branch, ahead, repo))
        print("np_git_publish: %s" % msg, file=sys.stderr)
        return False, msg
    if rebuilt:
        try:
            regen(repo)
        except Exception as exc:
            return False, "regenerate after sync failed: %s" % exc
        paths = [p for p in GENERATED if os.path.exists(os.path.join(repo, p))]
        if paths and _git(repo, "status", "--porcelain", "--", *paths)[1]:
            _git(repo, "add", "--", *paths)
            rc, _, err = _git(repo, "commit", "-q", "-m",
                              "sync: rebuild generated files after rebase", "--", *paths)
            if rc != 0:
                return False, "commit of rebuilt files failed: %s" % _one_line(err)
    return True, ""


# Files rebuilt from a source, never merged by hand.
GENERATED = ("dashboard/data/metrics.js",)


def _rebase(repo, base):
    """Rebase HEAD onto base, resolving what is safe. (rc, why, rebuilt)."""
    env = ["-c", "core.editor=true"]
    rc, _, err = _git(repo, *env, "rebase", "-q", base)
    rebuilt = False
    for _ in range(1000):
        if rc == 0:
            # A rebase that replayed a generated file may leave it stale.
            return 0, "", rebuilt or _touches_generated(repo, base)
        files = _git(repo, "diff", "--name-only", "--diff-filter=U")[1].split()
        if not files:
            # Stopped with nothing unmerged: an emptied commit, or a real error.
            if _rebase_in_progress(repo) and not _git(repo, "diff", "--cached", "--quiet")[0]:
                rc, _, err = _git(repo, *env, "rebase", "--skip")
                continue
            break
        bad = [f for f in files if not _resolve(repo, f)]
        if bad:
            _git(repo, "rebase", "--abort")
            return 1, ", ".join(bad), False
        rebuilt = rebuilt or any(f in GENERATED for f in files)
        _git(repo, "add", "--", *files)
        if _git(repo, "diff", "--cached", "--quiet")[0] == 0:
            rc, _, err = _git(repo, *env, "rebase", "--skip")
        else:
            rc, _, err = _git(repo, *env, "rebase", "--continue")
    _git(repo, "rebase", "--abort")
    return 1, _one_line(err) or "rebase failed", False


def _rebase_in_progress(repo):
    rc, gd, _ = _git(repo, "rev-parse", "--git-dir")
    if rc != 0 or not gd:
        return False
    gd = gd if os.path.isabs(gd) else os.path.join(repo, gd)
    return any(os.path.exists(os.path.join(gd, d)) for d in ("rebase-merge", "rebase-apply"))


def _touches_generated(repo, base):
    changed = _git(repo, "diff", "--name-only", base, "HEAD")[1].split()
    return any(f in GENERATED or f.endswith("metrics.jsonl") for f in changed)


def _resolve(repo, path):
    """Resolve one conflicted path in place. False when it needs a person.

    In a rebase, stage 2 is origin's side and stage 3 is the local commit.
    """
    if path in GENERATED:
        # --ours is origin here. Take it, then rebuild after the rebase.
        return _git(repo, "checkout", "--ours", "--", path)[0] == 0
    if not path.endswith(".jsonl"):
        return False
    rc2, origin_side, _ = _show_raw(repo, ":2:" + path)
    rc3, local_side, _ = _show_raw(repo, ":3:" + path)
    if rc2 != 0 or rc3 != 0:  # deleted on one side
        return False
    seen = set()
    out = []
    for line in origin_side.splitlines() + local_side.splitlines():
        if line.strip() and line not in seen:
            seen.add(line)
            out.append(line)
    try:
        with open(os.path.join(repo, path), "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
    except OSError as exc:
        print("np_git_publish: cannot write union of %s: %s" % (path, exc),
              file=sys.stderr)
        return False
    return True


def _show_raw(repo, spec):
    try:
        r = subprocess.run(["git", "-C", repo, "show", spec], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        return 1, "", str(exc)
    return r.returncode, r.stdout, r.stderr


def rebuild_generated(repo):
    """Rebuild dashboard/data/metrics.js from metrics.jsonl, as np_aggregate does."""
    src = os.path.join(repo, "dashboard", "data", "metrics.jsonl")
    out = os.path.join(repo, "dashboard", "data", "metrics.js")
    if not (os.path.isfile(src) and os.path.isfile(out)):
        return
    build = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "dashboard", "build.py")
    import np_aggregate  # lazy: np_aggregate imports this module
    # Raise on failure. _sync turns it into a failed publish, so a stale
    # metrics.js never reaches origin.
    r = subprocess.run([sys.executable, build, src, out], env=np_aggregate.dashboard_env(repo),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError("build.py exit %d: %s" % (r.returncode, _one_line(r.stderr)))


def _is_behind(detail):
    return "fetch first" in detail or "non-fast-forward" in detail


def _clean(repo):
    r = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                       capture_output=True, text=True)
    return r.returncode == 0 and not r.stdout.strip()


def _push_once(repo, branch):
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


def main(argv):
    """CLI for agentic crons: `np_git_publish.py push <repo> [branch]`."""
    if len(argv) < 2 or argv[0] != "push":
        print("usage: np_git_publish.py push <repo> [branch]", file=sys.stderr)
        return 2
    branch = argv[2] if len(argv) > 2 else "main"
    ok, why = publish(argv[1], branch)
    if not ok:
        print("np_git_publish: %s" % why, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "nervepack_engine"))
    sys.exit(main(sys.argv[1:]))
