---
id: 0092
status: accepted
date: 2026-10-16
tier: high
blast_radius:
  - agents/np-flow-kb-promote-scan.md
  - agents/README.md
  - docs/ARCHITECTURE.md
  - engine/setup/np_scheduler_install.py
  - engine/setup/tests/nervepack_engine/test_np_scheduler_install.py
  - change-specs/feat-kb-promote-weekday-schedule.md
---

# 0092: kb-promote-scan weekday schedule

## Context and problem statement

The `kb-promote-scan` cron runs once a week, Monday 08:45. Promotion lags up to
a week. The scheduler table supports one weekday per weekly job, so a
Monday-to-Friday job cannot be expressed.

## Considered options

1. Five table rows, one per weekday. Bad, because it breaks the one-row-per-job
   contract the installers and job health rely on.
2. Let the weekday field carry a range, and render it per backend. Good,
   because cron and schtasks take ranges natively, and launchd takes an array.

## Decision

We will run `kb-promote-scan` Monday to Friday at 11:00 local.

Chosen option: "range in the weekday field", because it keeps one row per job.
The cron field becomes `1-5`, the schtasks day becomes `MON,TUE,WED,THU,FRI`,
and the launchd plist gets a `StartCalendarInterval` array of five dicts.
Single-day and daily jobs render the same bytes as before.

## Non-goals

The data-base-side skill and the agent phases do not change. The agent's
"already ran today" guard keeps a day to one PR.

## Cross-cutting concerns

- Security: none. No new permission or secret.
- Privacy: none.
- Observability: `kb-promote-scan.log` and the freshness check are unchanged.

## Consequences

- Good, because promotion lags at most one working day.
- Bad, because the job runs five times a week and costs five scans, not one.
- Neutral, because the freshness threshold stays at 7 days.

## Confirmation

`test_np_scheduler_install.py` asserts the cron line `0 11 * * 1-5` and five
launchd weekday dicts at 11:00, with no Saturday or Sunday entry.

## Rollback

1. Revert the PR, or set the `kb-promote-scan` row in `_JOBS` back to `8, 45, ("1", "MON")`.
2. Re-run `cli.py setup install-memory-launchd` on macOS. On Linux run `install-memory-cron`. On Windows run `install-memory-schtasks`.
3. Confirm with `plutil -lint ~/Library/LaunchAgents/com.nervepack.kb-promote-scan.plist`.

## Deviations

None.
