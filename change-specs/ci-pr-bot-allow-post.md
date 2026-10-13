---
id: 0074
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - .github/workflows/claude-pr-review.yml
  - change-specs/ci-pr-bot-allow-post.md
---

# 0074: Let the PR review bot post its review

## Context and problem statement

With `--comment`, the bot writes a review and calls `gh pr review`. The action
denies that call, since no rule allows it. The transcript records the denial.

## Decision

Allow only `gh pr view`, `gh pr diff` and `gh pr comment`. Deny `gh pr review`,
`gh pr merge`, `gh api`, Edit and Write. Check out without persisted git
credentials so a `--body-file` comment has no token file to leak.

## Non-goals

No file edits, pushes, or general `gh api` access for the review job.

## Cross-cutting concerns

- Security: the job can read the PR and post a comment. It cannot approve,
  merge, or call the raw API, so an injected PR can't approve itself.
  `contents` stays read-only.

## Rollback

Revert this commit. The bot reviews without posting, as before.
