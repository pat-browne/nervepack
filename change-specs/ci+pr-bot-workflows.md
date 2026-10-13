---
id: 0070
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - .github/workflows/claude-pr-review.yml
  - .github/workflows/claude-pr-respond.yml
  - .github/claude-review-standards.md
  - change-specs/ci+pr-bot-workflows.md
---

# 0070: PR review and comment responder workflows

## Context and problem statement

PRs here get no automated review, and review comments can sit unanswered.
Every comment should end in a fix or a reasoned no-op without a human prompt.

## Considered options

1. Answer comments in the interactive session only. Bad, because it depends on a
   session being open when the comment lands.
2. A comment-triggered Actions workflow. Good, because it fires on every comment.

## Decision

We will add `claude-pr-review.yml` (reviews each new PR) and
`claude-pr-respond.yml` (answers each review comment with a pushed fix or a
reasoned no-op, then resolves the thread).

## Non-goals

Auto-merge. The responder pushes fixes and replies. Merge still waits on CI.

## Cross-cutting concerns

- Security: the responder skips fork PRs and human commenters without write
  access. Comment text is treated as untrusted. Its replies carry a marker so it
  never re-triggers on itself.
- Privacy: none.
- Observability: each run is an Actions job on the PR.

## Consequences

- Good, because no comment goes unanswered.
- Bad, because each comment costs a model run.

## Confirmation

The workflows appear on the next PR. A test comment gets a marked reply.

## Rollback

Delete the two workflow files.

## Deviations
