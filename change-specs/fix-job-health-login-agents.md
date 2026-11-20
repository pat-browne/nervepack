---
id: 0120
status: accepted
date: 2026-11-19
tier: normal
blast_radius:
  - engine/nervepack_engine/np_job_health.py
---

# 0120: Stop job health showing false red

## Context and problem statement

Two health rows were red with no real fault. A login-only launchd agent (nas-smb) has no interval, so it was read as daily and flagged overdue. A log with no run header (aggregate-metrics) was judged on its last 20 lines, so an old NOT PUBLISHED line kept the job on warn.

## Considered options

- Read plist logs outside the log dir. Rejected: a test pins that restriction on purpose.
- Add run headers to every job. Larger change, left for later.
- Treat no-interval agents as having no cadence, and judge a headerless log by its newest line. Chosen.

## Decision

A plist with no StartInterval or StartCalendarInterval has no cadence and is never overdue. Its schedule reads "at login" or "on demand". A log with no run header is judged by its newest non-empty line.

## Non-goals

The six error rows come from a disabled usage allocation. No code change fixes them.

## Cross-cutting concerns

Rollback: `git revert` of the merge commit.
