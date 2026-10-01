---
id: 0043
status: proposed
date: 2026-10-01
tier: high
blast_radius:
  - .github/workflows/ci.yml
  - change-specs/ci-job-timeouts.md
---

# 0043: Job timeouts for every CI job

## Context and problem statement

No job in `ci.yml` set `timeout-minutes`, so each one inherited the GitHub
default of 6 hours. On 2026-10-01 both Regression suite runs on a PR hung in
their "Install jq" step for over 3 hours. Regression is a required check, so the
PR stayed blocked and nothing reported a failure.

## Decision

Every job gets `timeout-minutes`, set to about three times its normal runtime.

| Job | Normal | Timeout |
|---|---|---|
| diff-review | 9 min | 25 |
| windows | 5 min | 20 |
| regression, dashboard-e2e, windows-bashfree | 1 to 2 min | 15 |
| all others | under 1 min | 10 |

A hung job now fails within the timeout and can be re-run.

## Considered options

1. **Job-level timeouts** (chosen) - one line per job, covers any hung step.
2. **Step-level timeouts on package installs only** - rejected: it covers only
   the step that hung this time.

## Consequences

**Good.** A hang fails within 25 minutes at worst, not 6 hours.

**Bad.** A job that slows down past its limit fails and needs the limit raised.

## Confirmation

The pull request's own CI run finishes green with every job under its limit.

## Rollback

Revert the commit. No other file reads these values.
