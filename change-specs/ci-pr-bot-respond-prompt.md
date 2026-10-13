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
comments`, to always treat the triggering comment as in scope, and to match bot
logins with or without the `[bot]` suffix.

## Non-goals

No change to the tool allowlist, trust filter, or permission check.

## Cross-cutting concerns

- Security: the trusted author set is unchanged. Only the login spelling the
  prompt accepts now matches what GraphQL returns.

## Rollback

Revert this commit. The responder then misses those comments again.
