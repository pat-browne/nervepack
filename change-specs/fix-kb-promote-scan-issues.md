---
id: 0112
status: accepted
date: 2026-11-05
tier: normal
blast_radius:
  - agents/np-flow-kb-promote-scan.md
  - agents/README.md
  - docs/ARCHITECTURE.md
  - engine/setup/tests/maintain/test_np_kb_promote_scan.py
  - change-specs/fix-kb-promote-scan-issues.md
---

# 0112: kb-promote-scan files issues, not queue PRs

## Context and problem statement

The data-base review queue moved from `docs/reviews/queue.md` to GitHub Issues on 2026-10-19.
The skill this cron runs already files issues. The prompt still waited for a queue diff before it reviewed, committed and opened a PR.
Every run since then stopped at that check, and its four later phases were dead.

## Considered options

1. Rewrite the prompt to the issue flow. Good, because it matches the skill. Neutral, because no code changes.
2. Keep the PR phases for a future queue file. Bad, because the queue is frozen by team decision.

## Decision

We will drop the review, commit, PR and checks phases.
The agent reads data-base from a detached `origin/trunk` worktree, runs the skill, prints its report, and removes the worktree.
It never commits, pushes or opens a PR.

Chosen option: "Rewrite to the issue flow", because the skill already files issues.

## Non-goals

Widening what the skill treats as promotable. That change lives in data-base.
Per-layer autopromote settings in the dashboard. That is a separate feature.

## Cross-cutting concerns

- Security: the agent's only external write is `gh issue create`, done by the skill.
- Privacy: unchanged. The skill de-personalizes before filing.
- Observability: phase lines in `kb-promote-scan.log` are kept.

## Consequences

- Good, because the run log no longer reports a false "no promotable content".
- Neutral, because a worktree never holds commits, so setup removes old ones unconditionally.

## Confirmation

`engine/setup/tests/maintain/test_np_kb_promote_scan.py` pins the new rules and asserts no PR or queue step remains.
