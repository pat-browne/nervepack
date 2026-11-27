---
id: 0127
status: accepted
date: 2026-11-27
tier: high
blast_radius:
  - .github/workflows/ci.yml
  - .github/workflows/ci-heavy.yml
  - .github/workflows/claude-pr-review.yml
  - skills/np-flow-speed/**
  - skills/np-core-dispatch/**
  - INDEX.md
  - change-specs/ci-draft-prs-heavy-tier.md
---

# 0127: Draft PRs skip CI, heavy jobs run once per batch

## Context and problem statement

A parallel speed run pushed once per fix and reran every job each time. The
Playwright e2e job ran on every push though it never blocks a merge.

## Considered options

1. Skip CI on drafts, cancel superseded runs, move e2e to a label-triggered workflow. Good, because a PR runs CI only once it is ready. Bad, because a draft gets no early signal.
2. Keep CI on every push. Good, because no change. Bad, because each fix round reruns every job.

## Decision

Chosen option: option 1. Drafts skip every job. `ready_for_review` starts the
full run. The e2e job moves to `ci-heavy.yml`, triggered by the `merge-ready`
label and by pushes to main. Runs off main cancel when a newer push lands.

## Non-goals

Changing which checks are required, or what any gate checks.

## Cross-cutting concerns

- Security: no new permissions. `ci-heavy.yml` keeps `contents: read`.
- Required checks: a draft cannot merge, and marking it ready runs every required job.
- Observability: e2e still posts its job summary and artifact.

## Consequences

- Good, because fewer CI minutes per PR.
- Bad, because e2e no longer runs on each PR push.
- Neutral, because pushes to main still run both workflows.

## Rollback

Revert the PR. No state or secrets change.

## Confirmation

The PR's own run: drafts show skipped jobs, ready PRs show every required check.

## Deviations

None.
