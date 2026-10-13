---
id: 0068
status: accepted
date: 2026-10-13
tier: normal
blast_radius:
  - engine/nervepack_engine/np_turn_parse.py
  - engine/setup/tests/nervepack_engine/test_np_turn_parse.py
  - change-specs/fix-turn-parse-sdk-boundary.md
---

# 0068: Turn boundary for desktop-app prompts

## Context and problem statement

The turn gate finds the current turn by the last user record with `promptSource == "typed"`. The desktop app and SDK hosts record a prompt as `promptSource: "sdk"` with `origin.kind: "human"`. No boundary is found, so the parser scans the whole session. The deliver-diff check then flags markdown edited in earlier turns on every later turn.

## Considered options

1. Also accept `sdk` with a human origin. Good, because it matches what the host records and keeps synthetic records out.
2. Accept any `sdk` record. Bad, because task notifications also arrive as `sdk` records.

## Decision

We will treat `promptSource == "sdk"` with `origin.kind == "human"` as a turn boundary, alongside `typed`.

## Non-goals

`np_journal.py` and `np-transcript-extract.py` carry the same `typed` check. They get their own change.

## Cross-cutting concerns

- Security: none.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because the gate scores only the current turn on desktop hosts.
- Neutral, because CLI transcripts keep the `typed` path.

## Confirmation

`test_sdk_human_prompt_is_a_turn_boundary` and `test_sdk_record_without_human_origin_is_not_a_turn_boundary` in `test_np_turn_parse.py`.

## Deviations
