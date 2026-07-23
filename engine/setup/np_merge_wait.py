"""Pure-Python port of np-merge-wait.sh -- the nervepack concurrency
merge-gate waiter. Waits for a repo to go QUIET (refs + HEAD + working tree
stable across a full poll interval), then reports whether a branch is
merge-ready against a base.

Exit codes (preserved exactly from the bash original):
  0  CLEAN    -- quiet + merges cleanly + no policy issues
  2  ISSUES   -- quiet but conflicts and/or forbidden AI-attribution trailers
  3  TIMEOUT  -- repo never settled within the timeout

Read-only: never commits, merges, pushes, or mutates the repo -- only
observes and reports. Pairs with the np-flow-merge-gate skill.
"""
import hashlib
import re
import subprocess
import time

import np_bashlib


def _git(repo, *args, check=False):
    # run_killtree, not subprocess.run: matches the established precedent in
    # np_implement_suggestion.py's _git() -- a git subprocess can spawn a
    # credential-helper/gpg-agent child that outlives it, and plain
    # subprocess.run's timeout-then-drain fallback can then hang forever on
    # Windows if that child still holds the output pipe open.
    return np_bashlib.run_killtree(["git", "-C", repo] + list(args),
                                    stdin=subprocess.DEVNULL, timeout=60)


def sample_state(repo, state_cmd=None):
    """One state snapshot, hashed. state_cmd (if given) is a callable(repo) ->
    str, overriding the real git-based sample -- the test-injection seam
    NP_MERGEWAIT_STATE_CMD played in the bash original."""
    if state_cmd is not None:
        return state_cmd(repo)
    parts = []
    for args in (("show-ref",), ("symbolic-ref", "--quiet", "HEAD"), ("status", "--porcelain")):
        r = _git(repo, *args)
        parts.append(r.stdout or "")
    return hashlib.md5("".join(parts).encode("utf-8", "replace")).hexdigest()


def wait_and_check(repo, branch=None, base="origin/main", interval=60,
                    backoff=30, timeout=1800, settle=2, state_cmd=None):
    """Returns (exit_code, output_lines). exit_code: 0 CLEAN, 2 ISSUES,
    3 TIMEOUT. Raises ValueError (usage error, bash's exit 1) if branch can't
    be determined."""
    lines = []
    if not branch:
        r = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
        branch = (r.stdout or "").strip()
    if not branch:
        raise ValueError("could not determine branch (detached HEAD?)")

    lines.append("np-merge-wait: watching %s (branch '%s' vs '%s') for quiescence…"
                 % (repo, branch, base))
    start_time = time.time()
    iv = interval
    prev = None
    stable = 0
    while True:
        s = sample_state(repo, state_cmd)
        stable = stable + 1 if s == prev else 1
        prev = s
        if stable >= settle:
            lines.append("np-merge-wait: repo quiet (%d stable samples)." % stable)
            break
        elapsed = int(time.time() - start_time)
        if elapsed >= timeout:
            lines.append("np-merge-wait: still active after %ds (timeout %ds)."
                         % (elapsed, timeout))
            lines.append("RESULT: TIMEOUT")
            return 3, lines
        time.sleep(iv)
        iv += backoff

    issues = []

    # 1) Conflict check via merge-tree (git >=2.38 --write-tree exits nonzero
    #    on conflict).
    r = _git(repo, "merge-tree", "--write-tree", base, branch)
    if r.returncode != 0:
        issues.append("merge conflicts vs %s" % base)

    # 2) Forbidden AI-attribution trailers in the branch range.
    verify = _git(repo, "rev-parse", "--verify", "--quiet", base)
    if verify.returncode == 0:
        log = _git(repo, "log", "%s..%s" % (base, branch), "--format=%B")
        body = log.stdout or ""
        trailers = len(re.findall(r"co-authored-by:\s*claude|generated with .*claude", body, re.IGNORECASE))
        if trailers > 0:
            issues.append("%d commit(s) carry a forbidden AI-attribution trailer" % trailers)

    if not issues:
        lines.append("np-merge-wait: '%s' merges cleanly into '%s'; no policy issues." % (branch, base))
        lines.append("RESULT: CLEAN")
        return 0, lines

    lines.append("np-merge-wait: '%s' is NOT ready to merge into '%s':" % (branch, base))
    for i in issues:
        lines.append("  - %s" % i)
    lines.append("RESULT: ISSUES (%d)" % len(issues))
    return 2, lines
