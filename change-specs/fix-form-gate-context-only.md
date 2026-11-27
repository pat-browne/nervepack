---
id: 0115
status: accepted
date: 2026-11-12
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/setup/tests/nervepack_engine/test_form_gate.py
  - engine/setup/tests/nervepack_engine/test_form_gate_composition.py
  - engine/setup/tests/nervepack_engine/test_form_gate_coverage.py
  - docs/ARCHITECTURE.md
  - change-specs/fix-form-gate-context-only.md
---

# 0115: form gate warn and rate channels add context only

## Context and problem statement

Spec 0114 made the third strike in block mode abstain. The `categorical=warn` and rate channels still returned `permissionDecision: allow` with context.

An allow overrides Claude Code's own permission checks for the whole tool call.

## Considered options

1. Keep `allow`. Bad, because it bypasses the normal permission system.

2. Return context only, with no `permissionDecision`. Good, because the normal permission system decides. Chosen.

## Decision

The warn and rate paths return `_context_only`. `categorical=ask` still returns `ask`. `_allow_with_context` is deleted, since nothing else calls it.

## Non-goals

The `ask` and `block` behavior does not change.

## Cross-cutting concerns

- Security: warn and rate output no longer override Claude Code's permission checks.

- Privacy: no new data is written.

- Observability: signals are unchanged.

## Consequences

- Good, because a warning never grants permission.

- Bad, because none known. The context text is unchanged.

## Confirmation

`test_form_gate.py` asserts that warn and rate output carries `additionalContext` and no `permissionDecision`.

## Rollback

`git revert` the merge commit. No hook registration changes.

## Deviations

(none)
