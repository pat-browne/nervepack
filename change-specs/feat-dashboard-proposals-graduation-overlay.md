---
id: 0064
status: accepted
date: 2026-10-13
tier: high
blast_radius:
  - dashboard/build.py
  - dashboard/index.html
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - agents/np-flow-apply-compact-proposal.md
  - agents/np-flow-graduate-candidate.md
  - engine/nervepack_engine/cli.py
  - engine/nervepack_engine/np_model.py
  - engine/setup/np-dashboard-server.py
  - engine/setup/np_dashboard_actions.py
  - engine/setup/np_implement_suggestion.py
  - engine/setup/tests/e2e/**
  - engine/setup/tests/evaluator/**
  - change-specs/feat-dashboard-proposals-graduation-overlay.md
---

# 0064: Dashboard proposal, graduation, and viewer actions

## Context and problem statement

Compact proposals and graduation candidates showed with no way to act on them.
The suggestions list grew long. Wiki and settings pages lost the reader's place.

## Considered options

1. Reuse the implement queue with job kinds. Good, because one queue and lock.
   Bad, because kind jobs read untrusted text.

2. A separate job runner. Bad, because it duplicates locking and status.

## Decision

We will add `--kind=compact|graduate` to the implement job. A kind job has its
own prompt and starts in the content overlay.

A kind job runs restricted. It has no Bash tool and uses `acceptEdits`, not
`bypassPermissions`. The harness commits for it and always lands a PR.

Reject and Dismiss write files directly. Suggestions page at 10. Wiki, skill,
and settings pages open in a sandboxed iframe overlay.

## Non-goals

Auto-merging kind-job PRs. A human reviews each one.

## Cross-cutting concerns

- Security: kind jobs get no shell and never land direct.

- Security: iframes use a scoped sandbox and no referrer.

- Privacy: no new data leaves the machine.

- Observability: kind jobs report through the implement-status file.

## Consequences

- Good, because proposals and candidates are actionable from the dashboard.

- Bad, because a kind job cannot run tests itself.

## Confirmation

`test_implement_kinds.py` asserts kind jobs get no Bash, no bypass, and never
land direct. The dashboard action, server, and static panel tests cover the rest.

## Rollback

Revert the squash commit. No data migration is needed.

## Deviations
