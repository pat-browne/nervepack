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
   progress on the default branch. Wait for any that is.
2. **Branch.** `git switch -c integrate/<date> origin/<default>`.
3. **Merge in order.** `git merge --no-ff origin/<branch>` for each PR. Put
   infra PRs first and PRs that touch the same files next to each other.
   Resolve each conflict keeping both sides' intent, and note the resolution.
4. **Gate locally.** Run the repo's full test suite. For infra, run validate
   and a read-only plan, and list every change. Abort on any destroy or
   replace that no source PR asked for.
5. **Free the runner.** Cancel queued CI runs for the source branches, since
   the integration PR supersedes them.
6. **One PR.** Its body lists each source PR, the conflict resolutions, the
   plan summary and the test results. Wait for green and fix real failures on
   the integration branch.
7. **Merge once.** Squash-merge, then watch the single apply. Hand-apply only
   what the CI role cannot, with a targeted plan first.
8. **Close the sources.** Comment "Landed in #N (<sha>)" on each, close it, and
   delete its branch.
9. **Verify live** once for the whole batch, as in the finish line.
