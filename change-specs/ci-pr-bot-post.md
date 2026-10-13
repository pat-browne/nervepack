---
id: 0073
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - .github/workflows/claude-pr-review.yml
  - change-specs/ci-pr-bot-post.md
---

# 0073: Make the PR review bot post its findings

## Context and problem statement

The review job finds real issues but posts nothing. The transcript shows
`/code-review:code-review` resolves to the built-in review, which reports
findings in-run and only posts to the PR when passed `--comment`.

## Decision

Pass `--comment` in the review prompt.

## Non-goals

No change to triggers, permissions, or standards.

## Cross-cutting concerns

- Security: unchanged. The job already holds `pull-requests: write`.

## Rollback

Revert this commit. The job then reviews without posting, as before.
