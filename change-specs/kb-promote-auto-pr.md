---
id: 0112
status: proposed
date: 2026-11-03
tier: standard
blast_radius:
  - agents/np-flow-kb-promote-scan.md
  - docs/ROADMAP.md
  - change-specs/kb-promote-auto-pr.md
---

# 0112: KB promote scan opens auto-merging doc PRs

## Context and problem statement

The weekday scan queued items in a review queue that is now frozen, and the
host skill files issues instead. Nobody acts on those, so promotable content
stalls.

## Considered options

1. Keep filing issues. Neutral, because it matches the host skill. Bad, because the work still waits on a person.
2. Write the docs and open a PR that auto-merges on green checks. Good, because content lands without a person. Bad, because it needs a guard proof, deferred in the roadmap.

## Decision

We will have the job write the docs, run lint and tests, open a PR, and enable
auto-merge only when lint, tests, and the required integrity check pass.

Chosen option: "Write docs and auto-merge", because the host repo requires the
integrity check on trunk and enabled auto-merge. The job opens a draft PR with
no auto-merge when the review receipt cannot be produced.

## Non-goals

Writing outside `docs/` and raising the cap of 3 docs per run. The roadmap entry gates both.

## Cross-cutting concerns

- Security: the job never pushes to trunk and never merges manually.
- Privacy: the PII and secret scrub rules stay.
- Observability: each phase prints a log line to the cron log.

## Consequences

- Good, because promoted docs reach the knowledge base without manual work.
- Bad, because no automated path allowlist exists yet.
- Neutral, because the model stays Sonnet via the existing seam.

## Confirmation

Read the prompt phases. Phase 9 gates auto-merge on draft state, lint, tests, and the check.

## Deviations

None.
