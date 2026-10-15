---
id: 0086
status: accepted
date: 2026-10-14
tier: normal
blast_radius:
  - dashboard/index.html
  - engine/setup/tests/evaluator/test_dashboard_jobs_panel.py
  - change-specs/feat-dashboard-scheduled-jobs.md
---

# 0086: Scheduled jobs panel on the dashboard

## Context and problem statement

`GET /api/jobs` reports the health of every scheduled job. Only the doctor
reads it. A failing or overdue cron stays invisible on the dashboard.

## Considered options

1. Leave it in the doctor. Bad, because nobody runs the doctor daily.
2. Bake job health into the static build. Bad, because it goes stale between builds.
3. A served-mode panel that fetches `/api/jobs`. Good, because it is live and reuses the endpoint.

## Decision

We will add a "Scheduled jobs" panel below the ledger and latest-session row.
Each row shows name, status pill, last run age, overdue flag and toggle state.
Problem rows sort first and get a warning edge. A summary line counts errors,
warnings and overdue jobs. Static mode or an endpoint error shows a note that
the panel needs the dashboard server.

Chosen option: "served-mode panel", because it reads live state with no new backend code.

## Non-goals

Run or restart buttons. Changes to `np_job_health`.

## Cross-cutting concerns

- Security: none. Job names and fields pass through `esc()`.
- Privacy: none. Log paths are not rendered.
- Observability: improves it. Job failures show on the dashboard.

## Consequences

- Good, because a failing cron is visible at a glance.
- Bad, because the panel is empty-with-note in static mode.
- Neutral, because the endpoint stays gated by `maintain.job_health`.

## Confirmation

`engine/setup/tests/evaluator/test_dashboard_jobs_panel.py` guards the panel,
the fetch, the row fields, the summary and the fallback note.

## Rollback

Revert the commit.

## Deviations
