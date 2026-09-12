---
id: 0035
status: accepted
date: 2026-09-12
tier: normal
blast_radius:
  - engine/setup/toggle-schema.json
  - engine/setup/tests/toggles/test_gate_override_toggles.py
  - change-specs/**
---

# 0035: make gates.spec_review editable from the dashboard

## Context and problem statement

`gates.spec_review` shipped with a schema entry carrying a description and no
`type`.

`np_toggle_schema.validate()` cannot type-check an entry with no type. It
returns invalid, exactly as it does for a missing entry.

The dashboard settings panel renders such a param read-only. It refuses to
edit what it cannot type-check, by design.

So the one gate a human flips most often could not be flipped from the panel.

The CLI worked the whole time. Pat hit this while turning the spec and plan
review stops off for Spinjam work.

The three sibling keys in the same family all carry `type: bool`.

## Considered options

1. **Add `"type": "bool"` to the existing entry.**

   Good, because it is the shape `gates.spec_guard.enforce` already uses.

   Good, because it needs no new code. Bad, because nothing.

2. **Special-case the key in `np-dashboard-server.py`.**

   Bad, because it bypasses the schema contract.

   That contract is what stops the panel editing a value it cannot validate.

3. **Leave it read-only and flip it by CLI only.**

   Bad, because Pat asked for the dashboard control.

   Neutral, because the CLI path already worked.

## Decision

Add `"type": "bool"` to the `gates.spec_review` entry in
`toggle-schema.json`.

Extend `test_gate_override_toggles.py` so the key must carry a bool type and a
description.

Chosen option 1. The sibling keys set the precedent and it costs no new code.

## Non-goals

- **Changing the hook's behavior.**

  `spec_review.py` reads the key exactly as before.

- **Changing the default.**

  The key still defaults on, and its scope stays local.

- **Reaching CI.**

  A local toggle cannot weaken a required check, and must not.

- **Adding the key to `GATE_KEYS`.**

  That tuple holds the three `.enforce` params. This key has a different
  shape, so it gets its own assertion.

## Cross-cutting concerns

- **Security:** none added. The key binds one machine through
  `~/.config/nervepack/toggles.local`.

- **Privacy:** no personal data. The schema file is already committed.

- **Observability:** unchanged. The hook logs its decision whatever the value
  reads.

The scope boundary is the security-relevant part.

This key gates a local PreToolUse hook only. It cannot reach a CI-enforced
required check.

Those run with no access to the local toggle file.

## Consequences

- Good, because the panel now renders a real control for the key.

- Good, because the test fails if a future edit drops the type.

- Neutral, because the default stays on. Nothing changes for anyone who never
  flips it.

- Bad, because the schema and the test must stay in step. The new test is what
  catches that.

## Confirmation

The new assertion failed before the change with `AssertionError: None !=
'bool'`.

`test_gate_override_toggles.py` passes 6 tests after it.

`np_toggle_schema.validate('gates.spec_review', 'off')` returns
`(True, False, None)`.

A bad value is rejected with `expected on/off, got 'banana'`.

The full regression suite ran as CI runs it. 182 passed, 0 failed, in 77s.

## Deviations

None. The change stayed inside the declared blast radius.
