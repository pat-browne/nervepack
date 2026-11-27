---
id: 0114
status: accepted
date: 2026-11-12
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/tests/nervepack_engine/test_form_gate.py
  - docs/ARCHITECTURE.md
  - change-specs/fix-form-gate-escalate-allow.md
---

# 0114: form gate third strike abstains

## Context and problem statement

In `categorical=block` mode the form gate denied a write twice. The third try returned `ask`, a permission prompt.

The prompt fired on routine source writes. A guard that prompts on routine work is a bug.

## Considered options

1. Keep `ask`. Bad, because it prompts on routine work.

2. Return `permissionDecision: allow` with context. Bad, because an allow overrides Claude Code's own permission checks.

3. Return context only, with no `permissionDecision`. Good, because the normal permission system decides. Chosen.

## Decision

On the third strike the gate adds `additionalContext` naming the findings and returns no permission decision.

It keeps the `form-gate-escalation` signal and the struggle record. A failed retry-counter write takes the same path. The two denies before escalation stay.

## Non-goals

The `warn` channel and the rate channel keep their current output.

## Cross-cutting concerns

- Security: the escalation path no longer overrides Claude Code's permission checks.

- Privacy: no new data is written.

- Observability: signal and struggle record are unchanged.

## Consequences

- Good, because no prompt appears on routine writes.

- Bad, because a write that never settles now lands. The struggle record surfaces the rule for tuning.

## Confirmation

`test_form_gate.py` asserts that escalation output carries no `permissionDecision` and that a failed counter write abstains.

## Rollback

`git revert` the merge commit. No hook registration changes.

## Deviations

(none)
