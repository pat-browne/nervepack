---
id: 0077
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - .github/workflows/claude-pr-respond.yml
  - change-specs/ci-pr-bot-push-rule.md
---

# 0077: Responder push rule that matches

## Context and problem statement

A live run committed the right fix but every push was denied. The rule
`Bash(git push origin HEAD:*)` is a prefix rule on `git push origin HEAD`, so
`git push origin HEAD:<branch>` never matches it. The commit also carried a
`Co-Authored-By` trailer, which the repo forbids.

## Decision

Allow exactly `git push origin HEAD:<this PR's branch>`, and tell the
responder to use that command with no prefix and no attribution trailer.

## Non-goals

No change to the trust filter or the other allowed tools.

## Cross-cutting concerns

- Security: narrower than before. The only allowed push targets this PR's
  branch. Force-push stays denied.

## Rollback

Revert this commit. Pushes are then denied again.
