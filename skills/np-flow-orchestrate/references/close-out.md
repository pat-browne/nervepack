# Close-out: capture, then archive

This section owns the rule for every coordinator, including [[np-core-dispatch]]
and [[np-flow-speed]]. A child that met its stated goal and sits idle gets closed
out, never left open.

1. Confirm the goal is met from evidence: merged PR, pushed commit, or report
   verified. A child still owed a step (live checks, a merge, an answer) stays
   open.
2. Send it [[np-core-capture-learning]] as one message. Tell it to take no new
   work after the capture.
3. Wait for its capture report. Check where the capture landed: a commit, a
   branch, or memory.
4. Run `git -C "$worktree" status -sb`, where `$worktree` is the child's
   working directory. Archive only when the tree is clean and the branch is not
   ahead of its remote. Otherwise, or if the command fails (missing worktree,
   git error), ask the child to commit and push, or leave it open as
   `waiting on me`.
5. Archive the child. Mark its row in § The ledger `done`, with the PR if one
   exists and the capture location.

A child that ends its turn on a gate or a question, with no capture report,
stays open as `waiting on me`. Archiving can remove the child's folder. Never
archive a child whose folder another live session uses.
