## After pushing an engine PR, verify CI before calling it done

A push is not done. Resolving review threads is not done either. Once CI
finishes, run `gh pr checks <N>`. Read the actual result, not just the
review-thread state.

On a past PR, review comments were resolved and the threads closed. Meanwhile
`spec-guard` and `tier-gate` were both failing in CI, unchecked.

The miss: `engine/setup/risk-tiers.json` lists paths that force a higher tier
when touched. That higher tier requires a matching
`change-specs/<branch-slug>.md` file to exist. Nobody ran `gh pr checks`
after pushing, so the missing file sat unnoticed.

Before reporting a PR ready or green: run the checks command, or check the
GitHub web UI's Checks tab if `gh` is unavailable. Read every failed or
still-pending row's log output, not just its name -- for `spec-guard` and
`tier-gate` failures specifically, check `change-specs/README.md` first.

Do not infer PR health from review threads, from your own commit succeeding,
or from the automated diff-review workflow's comments alone -- that workflow
never blocks merge, it only comments.

See `change-specs/README.md` for when normal/high tier changes need a spec.

### A stuck `BLOCKED` merge means re-check checks and threads, not platform lag

`required_review_thread_resolution` blocks merge on any unresolved review
thread, including one opened after your last check.

After every push, rerun, or thread resolution, re-query both: `gh pr checks
<N>` for status checks, and `gh pr view <N> --json reviews` for review state.
Don't assume a persistent `BLOCKED` or pending state is platform lag without
re-verifying both first.
