---
id: 0064
status: accepted
date: 2026-10-13
tier: normal
blast_radius:
  - engine/setup/np-dashboard-server.py
  - engine/setup/toggle-schema.json
  - engine/setup/toggles.conf
  - engine/setup/tests/journal/test_np_journal.py
  - change-specs/fix-async-probe-claim-lock.md
---

# 0064: Serialize the model probe claim and drop the unused journal.model param

## Context and problem statement

The dashboard server is threaded. Two probe requests at once could both pass the
stale-marker check in `claim_probe` and start two probes. A failed probe spawn was
not logged. Separately, the `journal.model` param was declared and shown in settings
but never read.

## Considered options

1. In-process lock around the claim, plus a spawn-failure log line. Good, because one server owns the marker.
2. A file lock in `np_model`. Bad, because it adds cross-platform locking for a one-server race.

## Decision

We will hold a `threading.Lock` around `claim_probe` in the server, log spawn
failures, and remove `journal.model` from the manifest and schema.

Chosen option: "in-process lock", because the race lives inside one server.

## Non-goals

Locking across separate server processes.

## Cross-cutting concerns

- Security: none.
- Privacy: none.
- Observability: a spawn failure now writes a log line.

## Consequences

- Good, because concurrent probe clicks start one probe.
- Good, because settings no longer show a param that does nothing.

## Confirmation

Existing probe and toggle-schema tests. Full suite green.

## Rollback

Revert this PR.

## Deviations
