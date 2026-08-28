---
id: 0022
status: proposed
date: 2026-08-28
tier: normal
blast_radius:
  - engine/nervepack_engine/np_git_publish.py
  - engine/nervepack_engine/np_toggle.py
  - engine/setup/np_aggregate.py
  - engine/setup/np_skill_maintain.py
  - engine/setup/tests/evaluator/test_np_git_publish.py
  - engine/setup/tests/evaluator/test_np_aggregate.py
  - engine/setup/tests/content/test_writer_implicit_fallback.sh
  - CHANGELOG.md
  - change-specs/**
---

# 0022: guard the crons' publish step on the branch, and stop discarding the result

## Context and problem statement

Three scheduled writers publish with the same two lines:

```python
subprocess.run(["git", "-C", repo, "push", "-q", "origin", "HEAD:main"],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
```

`np_aggregate.py:189`, `np_skill_maintain.py:311`, `np_toggle.py:475`.

Two faults compound. The refspec names `HEAD` without checking that HEAD is
`main`, and the result is thrown away. Park a checkout on a feature branch and
every push becomes a rejected non-fast-forward while the job still exits 0.

Observed 2026-08-28 on `nervepack-content`. Thirty-three cron commits
accumulated over two days on `capture/cube-databricks-auth-traps`, a branch 198
commits behind `main`. Nothing surfaced it: `launchctl list` reported last exit
status 0 for all six jobs, and the logs recorded successful runs. The stranding
mattered because `~/.claude/skills/*` symlink into that checkout, so skills
`skill-maintain` had split were unreadable on that machine, and skills merged to
`main` were invisible there.

`np_sync.py` compounds the diagnosis rather than causing it. It compares `HEAD`
to `origin/main` without checking that `HEAD` **is** `main`, so a parked branch
reports as "N behind" instead of "wrong branch".

## Considered options

1. **Push to the current branch instead of `main`.** Good, because no data
   stalls. Bad, because it scatters cron bookkeeping across whatever branches
   happen to be checked out, which is the mess this incident already made.
   Rejected.
2. **Keep pushing `HEAD:main` but check the result and log a failure.** Good,
   minimal. Bad, because it still attempts a push that cannot succeed and the
   operator learns only from a rejection message, not from the actual cause.
3. **Refuse when HEAD is not `main`, and surface a rejected push.** Chosen. The
   commit stays safe in the local branch, and the reason names the branch, which
   is the fact the operator needs.
4. **Make the crons switch the checkout to `main` themselves.** Rejected
   outright. A background job must never move a branch under an interactive
   session that has uncommitted work, which is exactly the situation found here.

## Decision

Add `np_git_publish.push_to_main(repo)` returning `(ok, detail)`. It refuses on
a non-`main` HEAD, a detached HEAD, and a non-repo; it returns git's stderr on a
rejected push; it never raises, because a scheduled job must not die in its
publish step. Each caller prints the reason to stderr and appends it to the
status string it already returned.

`NP_AGG_NO_PUSH=1` mirrors the existing `SKILL_MAINTAIN_NO_PUSH=1` so the
`np_aggregate` tests that cover commit behaviour do not report a publish failure
they never wanted from a sandbox with no reachable origin.

## Non-goals

`np_sync` reporting "HEAD is not main" as its own outcome. That belongs with the
sync contract's five documented outcomes and its status-file format, which this
change does not touch.

Retiring the three local `_git` helpers in favour of one shared git wrapper.
Tempting while here, and out of scope: each has different output handling that
other call sites in those modules depend on.

## Consequences

A cron whose checkout is parked now says so, every run, in its status line and
on stderr, and its commit waits locally. That is louder than before and is the
point. An operator who ignores it still loses nothing but time, because the
commits accumulate exactly as they did during the incident.

`test_writer_implicit_fallback.sh` had to change. It builds a hermetic minimal
engine and copied only `np_toggle.py` and `np_content.py`. `np_git_publish` is a
dependency of both callers, so the sandbox raised ImportError and the fixture's
fail-open assertion reported it as a non-zero exit. It now copies the module.
