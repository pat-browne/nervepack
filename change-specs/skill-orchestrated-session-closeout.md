---
id: 0100
status: accepted
date: 2026-10-26
tier: standard
blast_radius:
  - skills/np-flow-orchestrate/SKILL.md
  - skills/np-core-dispatch/SKILL.md
  - change-specs/skill-orchestrated-session-closeout.md
---

# 0100: Close out idle child sessions with capture, then archive

## Context and problem statement

A coordinator starts child sessions and leaves them open after their goal is
met. Their learnings go uncaptured and the sidebar fills with idle sessions.

## Considered options

1. State the rule once in `np-flow-orchestrate` and point to it from
   `np-core-dispatch`. Good, because one place owns it.
2. Repeat the steps in both skills. Bad, because the copies drift.

## Decision

We will add a "Close-out" section to `np-flow-orchestrate`. A child that met
its goal and sits idle gets a capture message, then is archived once the
capture lands. A child owed a step, stalled on a gate, or holding uncommitted
work stays open. `np-core-dispatch` gets a step that points to the section.

## Non-goals

No hook or cron enforces close-out. The rule is guidance only.

## Cross-cutting concerns

- Security: none.
- Privacy: company-neutral wording, no instance data.
- Observability: the ledger row records the capture location.

## Consequences

- Good, because learnings get captured before a session closes.
- Neutral, because each skill stays under the 8 KB budget.

## Confirmation

`bash engine/setup/tests/run-all.sh` and a size check that each edited
`SKILL.md` is under 8 KB.
