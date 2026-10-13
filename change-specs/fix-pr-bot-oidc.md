---
id: 0071
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - .github/workflows/claude-pr-review.yml
  - .github/workflows/claude-pr-respond.yml
  - change-specs/fix-pr-bot-oidc.md
---

# 0071: Grant id-token to the PR bot workflows

## Context and problem statement

Both PR bot workflows fail at start. `claude-code-action` fetches its GitHub App
token over OIDC, and neither workflow grants `id-token: write`.

## Decision

Add `id-token: write` to the permissions block of both workflows.

## Non-goals

No change to triggers, trust filters, or tool allowlists.

## Cross-cutting concerns

- Security: `id-token: write` only lets the job request an OIDC token for the
  action's own token exchange. It grants no repo write access.
