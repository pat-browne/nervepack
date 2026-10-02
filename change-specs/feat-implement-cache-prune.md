---
id: 0044
status: accepted
date: 2026-10-02
tier: normal
blast_radius:
  - engine/setup/np_implement_suggestion.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/tests/evaluator/test_implement_prune.py
  - change-specs/feat-implement-cache-prune.md
---

# 0044: Prune stale implement status and queue files

## Context and problem statement

The implement job writes one status file per suggestion to
`~/.cache/nervepack/implement-status/` and one entry per waiting job to
`implement-queue/`. Nothing ever deletes them, so the cache grows without bound.

## Considered options

1. Prune at job start. Good, because it needs no new cron or toggle family.
2. A separate daily cron. Bad, because it adds scheduler wiring for a tiny job.

## Decision

We will prune at the start of each implement job, before the lock is taken.
Files older than `evaluator.implement_status_ttl_days` (default 30, 0 disables)
are removed by mtime. Status files in state `queued` or `running` stay.
`running.json` stays while its pid is alive.

Chosen option: "Prune at job start", because it is the smallest change.

## Non-goals

Pruning `implement.log`. It is a single file and has its own concerns.

## Cross-cutting concerns

- Security: deletes only regular files in the two cache dirs, by fixed name rules.
- Privacy: none.
- Observability: logs one line with the count when files are removed.

## Consequences

- Good, because the cache stays bounded.
- Neutral, because a job older than the TTL loses its dashboard status row.

## Confirmation

`engine/setup/tests/evaluator/test_implement_prune.py`.

## Deviations
