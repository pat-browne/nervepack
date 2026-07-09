# Recovery recipes — when a dispatched agent goes wrong

Read on demand from the skill body's pointers. Two incident types.

## Stall salvage (agent died before committing)

A backgrounded agent can come to rest with an error — a watchdog stall ("no
progress for ~600s") — **before it commits**. Re-dispatching risks another stall
and throws away work it already did. Instead:

1. **Inspect its worktree** (`git -C <worktree> status` / `diff <base>`). A
   stalled agent usually has the implementation done but **uncommitted** — it
   typically dies during the final verify step, not mid-edit.
2. If the diff is sound, **finish it yourself**: commit it, add what it didn't
   reach (docs, a missing test), verify (suite + freshness), and integrate.
   Salvage beats restart.
3. Re-dispatch only if the worktree is empty or the work is unsound.

## Wrong-checkout reconcile (change landed in the wrong place)

When an agent's commit landed on the wrong branch/checkout (`main`, an
off-branch orphan, the main checkout instead of its worktree), reconcile
rather than re-run:

1. `git tag <backup-name> <sha>` — insurance before any history surgery.
2. `git cherry-pick <sha>` onto the **correct** branch.
3. Confirm content identity: `git diff <orphan> <cherry-pick>` is empty.
4. `git reset --hard origin/main` the polluted checkout.

Prevention: pin the worktree path emphatically in the dispatch prompt and have
the agent echo `git rev-parse --show-toplevel` before its first edit.
