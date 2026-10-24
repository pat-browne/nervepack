---
id: 0096
status: accepted
date: 2026-10-24
tier: high
blast_radius:
  - engine/nervepack_engine/np_checkout_guard.py
  - engine/nervepack_engine/hooks/checkout_guard.py
  - engine/nervepack_engine/np_doctor.py
  - engine/setup/tests/nervepack_engine/test_checkout_guard.py
  - change-specs/fix-checkout-guard-hardening.md
---

# 0096: checkout-guard hardening

## Context and problem statement

Spec 0095 shipped the stale-checkout guard. Review found three weaknesses:
overlay-resolution failure travelled through a module global, exception text
reached agent-facing output, and a git timeout in the first probe made a
checkout vanish instead of count as unknown.

## Considered options

1. Leave as is. Bad, because failures can read as clean and exception text is
   an injection channel.
2. Pass state through return values, emit fixed messages, and fence the doctor
   row. Good, because decisions depend only on arguments.

## Decision

We will make `checkouts()` return `(repos, overlay_error)` and `scan()` return
`(infos, overlay_error)`, with `warning()` and `doctor_status()` deciding from
arguments. Errors carry only `type(exc).__name__`. The doctor row wraps its
dynamic parts in nonce UNTRUSTED markers. `check()` returns None only when the
path is not a git repo; a timeout or OSError yields an all-unknown info that
blocks PASS.

Chosen option: 2.

## Non-goals

No change to what counts as stale.

## Cross-cutting concerns

- Security: no exception text or raw git strings reach the agent unfenced.
- Privacy: none.
- Observability: hook stderr names the exception type.

## Consequences

- Good, because failure modes cannot read as clean.
- Neutral, because `checkouts()`/`scan()` signatures changed; callers are in this module, the hook and tests.

## Confirmation

`engine/setup/tests/nervepack_engine/test_checkout_guard.py`.

## Rollback

Revert the squash commit.

## Deviations
