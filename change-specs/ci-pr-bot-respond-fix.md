---
id: 0075
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - .github/workflows/claude-pr-respond.yml
  - .github/workflows/claude-pr-review.yml
  - change-specs/ci-pr-bot-respond-fix.md
---

# 0075: Let the responder answer the review bot, and keep its transcript

## Context and problem statement

The review bot's comment triggers the responder, which then fails with
"Workflow initiated by non-human actor". The action needs bots named in
`allowed_bots`, even though our job filter already trusts them. A run on a
human comment had 3 denied tool calls that the hidden output can't explain.

## Decision

Set `allowed_bots` to the two bots the job filter trusts. Upload the execution
file as a 3-day artifact. Both transcript uploads use `continue-on-error`, so
an artifact outage never fails a review or response.

## Non-goals

No change to the trust filter, permission check, or tool allowlist.

## Cross-cutting concerns

- Security: `allowed_bots` matches the job filter's existing bot allowlist, so
  it widens nothing. The transcript holds PR text and tool output, no token.

## Rollback

Revert this commit. Bot comments then fail the action again, as before.
