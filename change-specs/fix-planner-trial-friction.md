---
id: 0116
status: accepted
date: 2026-11-12
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/nervepack_engine/hooks/turn_gate.py
  - engine/nervepack_engine/np_claims.py
  - engine/setup/tests/nervepack_engine/test_form_gate.py
  - engine/setup/tests/nervepack_engine/test_np_claims.py
  - engine/setup/tests/nervepack_engine/test_turn_gate.py
  - docs/ARCHITECTURE.md
  - change-specs/fix-planner-trial-friction.md
---

# 0116: Planning-plugin file exemption and read-only claims

## Context and problem statement

An orchestrator trial with a planning plugin hit two nervepack frictions.

The form gate blocked the plugin's plan and brief files twice. The plan agent then read hook source to get past it. The plugin owns the format of those files.

A read-only monitor session held a claim on the same branch. The orchestrator got a STOP and asked the user about it.

## Considered options

1. Add the plugin's paths to `exempt_globs` in the content overlay. Bad, because the paths sit in every repo and a glob per repo does not scale.
2. Add the plugin's paths to the built-in `_EXEMPT` pattern. Good, because it covers every repo and mirrors the existing test and build exemptions.
3. Detect read-only sessions from their tool calls. Bad, because the claim hook sees prompts, not tool calls.
4. Let a session declare phase `read-only`. Good, because it is explicit and needs no new field.

## Decision

We will add the plugin's plan directory and `briefs/<tracker_type>-<id>.md` to `_EXEMPT` in both prose gates. Spec 0118 later moved this exemption to `form_gate.exempt_globs`, set per machine.

We will treat a claim with phase `read-only` as a non-writer. It adds no STOP, overlap or rank, and a read-only session sees no STOP.

Chosen options: 2 and 4, because each is small and explicit.

## Non-goals

Other files in a `briefs/` folder stay gated. No automatic read-only detection.

## Cross-cutting concerns

- Security: none. The gates stay on for every other path.
- Privacy: none.
- Observability: the claims block still lists read-only peers under "Live now".

## Consequences

- Good, because plugin runs no longer fight the form gate.
- Good, because a monitor session no longer stalls an orchestrator.
- Bad, because a session that wrongly claims `read-only` hides a real conflict.

## Confirmation

The new tests in `test_form_gate.py` and `test_np_claims.py` cover both changes.

## Rollback

Revert the PR. No data or config format changes, so a revert needs no migration.
