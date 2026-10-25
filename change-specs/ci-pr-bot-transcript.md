---
id: 0072
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - .github/workflows/claude-pr-review.yml
  - change-specs/ci-pr-bot-transcript.md
---

# 0072: Keep the PR review transcript as a short-lived artifact

## Context and problem statement

The review job runs and exits clean, but posts nothing. The action hides the
model's output, so the cause can't be seen from the log.

## Decision

Upload the action's execution file as a workflow artifact kept for 3 days.

## Non-goals

No change to the review prompt, triggers, or permissions.

## Cross-cutting concerns

- Security: the transcript holds the PR diff and read-only `gh` output. The
  OAuth token is not in it. Artifacts expire after 3 days.

## Rollback

Revert this commit. The review job runs as before without the artifact.
