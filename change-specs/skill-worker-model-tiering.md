---
id: 0094
status: accepted
date: 2026-10-23
tier: standard
blast_radius:
  - skills/np-flow-orchestrate/SKILL.md
  - skills/np-core-dispatch/SKILL.md
  - skills/np-flow-speed/SKILL.md
  - change-specs/skill-worker-model-tiering.md
---

# 0094: Worker model tiering applies to sessions too

## Context and problem statement

`np-flow-speed` has a model table for subagent workers. Nothing applied it to
separate sessions, and the orchestrate and dispatch skills did not state it. A
coordinator started three Opus sessions because the session-start call
inherited its model.

## Considered options

1. State the rule once in `np-flow-orchestrate` and point to it from the other
   two skills. Good, because one place owns it and the table stays in one file.
2. Repeat the rule in all three skills. Bad, because the copies drift.

## Decision

We will add a "Worker models" section to `np-flow-orchestrate`. It says a
coordinator never lets a worker inherit its model, passes a model on every
subagent and session, and takes hard calls as decision requests. We will
replace the model sentence in `np-core-dispatch` and extend the spawn bullet in
`np-flow-speed` with a pointer to that section.

## Non-goals

No hook or toggle enforces the model argument. The rule is guidance only.

## Cross-cutting concerns

- Security: none.
- Privacy: company-neutral wording, no instance data.
- Observability: none.

## Consequences

- Good, because sessions stop inheriting the top-tier model.
- Neutral, because each skill stays under the 8 KB budget.

## Confirmation

`bash engine/setup/tests/run-all.sh` and a size check that each edited
`SKILL.md` is under 8 KB.
