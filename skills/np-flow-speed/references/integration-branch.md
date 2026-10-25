# Integration branch: landing several PRs at once

Serial merging costs one CI run and one infra apply per PR, and each merge
leaves the rest BEHIND. On a single runner that turns a batch into hours.
One integration branch pays those costs once.

## When to use it

- Default: two or more PRs from one run are ready, or CI is the bottleneck.
- Merge serially instead when two PRs conflict in meaning (not just text), or
  one carries risk you want to roll back alone (a migration, a destructive
  infra change).

## Steps

1. **Quiesce.** Check that no PR is mid-merge and no deploy or apply run is in
   progress on the default branch (`gh run list --branch <default>
   --status in_progress`). Wait for any that is.
2. **Branch.** `git switch -c integrate/<date> origin/<default>`.
3. **Merge in order.** `git merge --no-ff origin/<branch>` for each PR. Put
   infra PRs first and PRs that touch the same files next to each other.
   Resolve each text conflict keeping both sides' intent, and record each
   resolution for the PR body (step 6). A semantic conflict (incompatible changes to the same thing)
   means abort the integration and merge those PRs serially.
4. **Gate locally.** Run the repo's full test suite by the command in its CLAUDE.md or
   AGENTS.md, and keep the output. For infra, run the validate
   and read-only plan commands that doc names (e.g. `terraform validate`, `terraform plan`),
   and list every change. Read the plan's own summary for destroys and replaces; a grep alone can miss them.
   Abort on any destroy or replace that no source PR asked for, and name the source PR for each change in the PR body.

   **Abort cleanup:**
   - Delete the integration branch, local and remote.
   - Leave the source PRs open.
   - Re-run their CI only if step 5 already cancelled it.
   - Comment on each why the batch was abandoned.
5. **Free the runner.** Cancel queued and in-progress CI runs for the source branches, since
   the integration PR supersedes them.
6. **One PR.** Its body lists each source PR, the conflict resolutions, the
   plan summary and the test results. Wait for CI. If it fails, triage each failure:
   - Test or build failures that come from the integration itself (a
     conflict resolution): fix them on the integration branch.
   - A failure that belongs to one source PR: drop that PR from the batch
     and fix it on its own branch; re-run its CI if step 5 cancelled it. To drop one, rebuild the integration branch
     without it (reset to the default branch, re-merge the rest in order), then re-run the local gate before going on.
7. **Merge once.** Squash-merge, then watch the single apply. Hand-apply only
   what the CI role cannot. Hand-apply means:
   - A targeted plan, then an apply, of only the resources the CI role
     cannot change, run with the owner's credentials.
   - The plan shows 0 destroys.
   - A CI plan afterward shows no drift.

   **Rollback.** If the apply fails after the merge, either revert the merge
   commit or fix forward. Revert when the cause is unclear or the fix is not
   small and certain, since it restores the last known state fastest. Fix
   forward only when the cause is understood and the fix is a few lines. Then re-apply, pass the live check, and say which
   you chose.
8. **Close the sources.** Comment "Landed in #N (<sha>)" on each, close it, and
   delete its branch.
9. **Verify live** once for the whole batch, as in the finish line.
