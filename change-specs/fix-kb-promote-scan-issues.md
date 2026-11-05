---
id: 0113
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

# 0113: kb-promote-scan files issues, not queue PRs

## Context and problem statement

The data-base review queue moved from `docs/reviews/queue.md` to GitHub Issues on 2026-10-19.
The skill this cron runs already files issues. The prompt still waited for a queue diff before it reviewed, committed and opened a PR.
Every run since then stopped at that check, and its four later phases were dead.

## Considered options

1. Rewrite the prompt to the issue flow. Good, because it matches the skill. Neutral, because no code changes.
2. Keep the PR phases for a future queue file. Bad, because the queue is frozen by team decision.

## Decision

We will drop the queue review, commit, PR and checks phases.
The agent runs the skill in a detached `origin/trunk` worktree of data-base.
The skill writes docs and small skill additions, and files `triage` issues for new or large skills.
The agent runs data-base's CI gates and a scope gate on every changed path.
It pushes docs to `trunk`. Every data-base PR needs a pr-review receipt, so docs cannot auto-merge via PR.
Skill additions go to one PR without auto-merge. A person runs pr-review and merges it.
This replaces the auto-merge PR flow from the kb-promote-auto-pr spec.

Chosen option: "Rewrite to the issue flow", extended to push gated additions.

## Non-goals

The routing rules themselves. They live in the data-base skill and its own change.
Per-layer autopromote settings in the dashboard. That is a separate feature.

## Cross-cutting concerns

- Security: the agent pushes to data-base `trunk` and files issues. It never force-pushes or opens a PR.
- Privacy: the skill de-personalizes before writing or filing.
- Observability: phase lines in `kb-promote-scan.log`. The commit body lists every path written.

## Consequences

- Good, because harness knowledge reaches data-base without a manual review step.
- Bad, because a wrong doc lands on `trunk` before a person reads it. The gates and the team's trunk review catch it after.
- Neutral, because a worktree with an unpushed commit is kept for manual recovery.

## Confirmation

`engine/setup/tests/maintain/test_np_kb_promote_scan.py` pins the new rules and asserts no PR or queue step remains.
