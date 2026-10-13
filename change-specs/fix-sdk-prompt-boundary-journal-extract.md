---
id: 0066
status: accepted
date: 2026-10-13
tier: normal
blast_radius:
  - engine/nervepack_engine/np_journal.py
  - engine/setup/np-transcript-extract.py
  - engine/setup/tests/journal/test_np_journal.py
  - engine/setup/tests/episodic/test_transcript_extract.sh
  - change-specs/fix-sdk-prompt-boundary-journal-extract.md
---

# 0066: Recognize desktop-app prompts in the journal and transcript extractor

## Context and problem statement

`np_journal.py` and `np-transcript-extract.py` accept a user record as a real prompt only when `promptSource == "typed"`. The desktop app and SDK hosts record prompts as `promptSource: "sdk"` with `origin.kind: "human"`. Desktop sessions get no journal goal and no last instruction in the resume pointer.

## Considered options

1. Also accept `sdk` with a human origin. Good, because it matches what the host records and keeps task notifications out.
2. Accept any `sdk` record. Bad, because task notifications also arrive as `sdk` records.

## Decision

We will treat `promptSource == "sdk"` with `origin.kind == "human"` as a real prompt, alongside `typed`. Each file keeps a small local helper. A shared helper waits until the same fix in `np_turn_parse.py` (spec 0065) merges.

## Non-goals

`np_turn_parse.py` is covered by spec 0065.

## Cross-cutting concerns

- Security: none.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because desktop sessions get a journal goal and a resume pointer.
- Neutral, because CLI transcripts keep the `typed` path.

## Confirmation

`test_seed_sdk_human_prompt_sets_goal` and `test_seed_sdk_without_human_origin_is_not_a_prompt` in `test_np_journal.py`. The sdk cases in `test_transcript_extract.sh`.

## Deviations

None.
