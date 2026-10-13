---
id: 0076
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - .github/workflows/claude-pr-respond.yml
  - change-specs/ci-pr-bot-respond-prompt.md
---

# 0076: Responder finds conversation comments and bot threads

## Context and problem statement

A live run ignored an owner's PR comment and every bot review thread. It listed
conversation comments with REST `gh api`, which the allowlist denies. It
matched bots as `github-actions[bot]`, but GraphQL returns `github-actions`.

## Decision

Tell the responder to list conversation comments with `gh pr view --json
comments`, to always treat the triggering comment as in scope, and to accept a bot
only when GraphQL reports `__typename: Bot` with login `claude` or
`github-actions`. The triggering comment's id and author are passed in.

## Non-goals

No change to the tool allowlist, trust filter, or permission check.

## Cross-cutting concerns

- Security: the trusted author set is unchanged. A human account named
  `claude` fails the `__typename: Bot` check, so it gains nothing.

## Rollback

Revert this commit. The responder then misses those comments again.
