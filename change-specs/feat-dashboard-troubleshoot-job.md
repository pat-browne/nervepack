---
id: 0122
status: accepted
date: 2026-11-20
tier: normal
blast_radius:
  - dashboard/index.html
  - engine/setup/np-dashboard-server.py
  - engine/setup/np_implement_suggestion.py
  - agents/np-flow-troubleshoot-job.md
  - change-specs/feat-dashboard-troubleshoot-job.md
  - docs/ARCHITECTURE.md
  - engine/setup/tests/evaluator/test_dashboard_jobs_panel.py
  - engine/setup/tests/evaluator/test_dashboard_server.py
  - engine/setup/tests/evaluator/test_implement_kind_overlay.py
  - engine/setup/tests/evaluator/test_implement_kinds.py
  - engine/nervepack_engine/np_job_health.py
  - engine/setup/tests/maintain/test_np_job_health.py
---

# 0122: Troubleshoot button on unhealthy health-check rows

## Context and problem statement

The Health checks panel shows a failing scheduled job but offers no way to act.
The user must read the log and fix the job by hand.

## Considered options

1. Leave diagnosis to the user. Bad, because the panel only reports.
2. A new job runner. Bad, because it repeats preflight, dedupe and status polling.
3. A `troubleshoot` kind on the existing implement machinery. Good, because it reuses all of that.

## Decision

We will add a Troubleshoot button to each unhealthy row (served mode only) and
`POST /api/jobs/troubleshoot {name}`. The server checks the name against the live
survey, refuses a healthy job, and queues a `troubleshoot` job with text `job:<name>`.
The agent reads the job's log and schedule entry, then fixes code or config in the
repo or ends with `NOT_IMPLEMENTABLE: <diagnosis>`.

The kind tries the engine, then the content overlay. It keeps Bash, unlike the
compact and graduate kinds, because it must read logs and run launchctl and crontab. An engine
fix always lands as a PR. An overlay fix lands direct.

Chosen option: "new kind", because it reuses the queue, lock, worktree and status path.

## Non-goals

A credentials panel button. Fixing machine state outside the repo.

## Cross-cutting concerns

- Security: the name is checked against the survey, and the task text comes from the row name only. The prompt treats log text as untrusted. The agent runs with Bash and no restriction flag, so an engine fix always lands as a PR, never direct, and the agent never runs the job itself.
- Privacy: the prompt forbids printing secrets.
- Observability: the result shows on the row through the status file.

## Consequences

- Good, because a failing job can be fixed from the panel.
- Bad, because the kind runs an unrestricted agent with Bash.
- Neutral, because the endpoint stays gated by `maintain.job_health`.

## Confirmation

`test_implement_kinds.py`, `test_implement_kind_overlay.py`, `test_dashboard_server.py`
and `test_dashboard_jobs_panel.py`.

## Rollback

Revert the commit.

## Deviations
