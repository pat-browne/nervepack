---
id: 0099
status: accepted
date: 2026-10-26
tier: high
blast_radius:
  - engine/setup/np_git_publish.py
  - engine/setup/np_aggregate.py
  - engine/setup/np_agentic_cron.py
  - engine/setup/np_skill_maintain.py
  - engine/nervepack_engine/np_doctor.py
  - engine/onboard/capabilities.json
  - engine/setup/tests/evaluator/test_np_git_publish_route.py
  - engine/setup/tests/evaluator/test_np_aggregate.py
  - engine/setup/tests/content/test_writer_implicit_fallback.sh
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - change-specs/fix-cron-commit-off-main.md
---

# 0099: Crons never commit onto a non-main branch

## Context and problem statement

Scheduled writers commit into the live checkout of the engine or content repo.
`push_to_main` refuses to push when HEAD is not main. The commit has already
landed on the feature branch by then. This stranded 33 commits on 2026-08-28.
It stranded 114 commits by 2026-10-26.

## Considered options

1. Refuse every cron when off main. Good, because it is the smallest change. Bad,
   because metrics stop for as long as a person works on a branch.
2. Switch the live checkout to main for the run. Bad, because it changes files
   under an active session.
3. Route deterministic writers to a private worktree at origin/main, and refuse
   the model-driven ones. Good, because metrics keep flowing and nothing touches
   the live tree. Bad, because it adds one cached worktree per repo.

## Decision

We will add `off_main`, `write_root`, `cron_worktree` and `publish` to
`np_git_publish.py`. The aggregator writes and commits in the worktree that
`write_root` returns. The agentic crons and the skill-maintain split call
`off_main` and refuse with a `REFUSED` log line.

Chosen option: "3", because the aggregator writes known paths and moves cleanly.
The agentic crons hand a model live paths through prompts and content-dir
lookups. Redirecting them would need a prompt contract change, so they refuse.

## Non-goals

`np_toggle` commits on a user command, not a schedule, so it keeps its push
guard only. `kb-promote-scan` commits in its own worktree and is exempt.

## Cross-cutting concerns

- Security: the worktree sits under the per-user cache dir. No new credential.
- Privacy: no new data leaves the machine.
- Observability: one stderr or log line names the branch. The doctor
  `cron-branch` check WARNs on the same state.

## Consequences

- Good, because no cron commit can land on a feature branch.
- Bad, because agentic crons pause while a checkout sits off main.
- Neutral, because a live checkout on main keeps the old behavior.

## Confirmation

`engine/setup/tests/evaluator/test_np_git_publish_route.py` covers detection,
worktree reuse, publish, and the agentic refusal.
`test_np_aggregate.py::TestAggregateOffMain` proves the batch reaches origin/main
and the feature branch does not move.

## Rollback

Revert the squash commit. Then delete `~/.cache/nervepack/cron-worktrees/` and
run `git worktree prune` in each repo.

## Deviations
