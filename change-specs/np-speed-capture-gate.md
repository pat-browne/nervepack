---
id: 0107
status: proposed
date: 2026-10-31
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/post_ship_capture.py
  - skills/np-core-capture-learning/SKILL.md
  - skills/np-flow-speed/SKILL.md
  - skills/np-flow-speed/references/verify-and-rollback.md
  - change-specs/np-speed-capture-gate.md
  - engine/setup/tests/nervepack_engine/test_post_ship_capture.py
---

# 0107: Capture step in the speed finish line

## Context and problem statement

The speed flow ends at merge or deploy, the moment the post-ship capture hook
fires. The flow itself never named a capture step, and the skip rule in the
capture skill was loose enough that sessions skipped it by default.

## Considered options

1. Add a Capture step to the speed finish line and tighten the skip rule. Good,
   because the hook text, flow and skill then agree. Bad, because it is prose only.
2. Leave the hook as the only prompt. Bad, because a passive prompt gets skipped.

## Decision

We will add a Capture step to `np-flow-speed`, update the hook's injected text to
match, and make the skip rule in `np-core-capture-learning` stricter.

Chosen option: 1, because it changes wording only and needs no new code path.

## Non-goals

- No automatic capture. The session still decides what is worth keeping.

## Cross-cutting concerns

- Security: the hook change is injected text only. No new input is read.
- Privacy: the injected text still names no command.
- Observability: the existing `post-ship-capture` marker is unchanged.

## Consequences

- Good, because the flow, hook and skill give one consistent instruction.
- Bad, because a session may spend one extra skill call on a trivial change.

## Confirmation

`engine/setup/tests/nervepack_engine/test_post_ship_capture.py` covers the hook.

## Rollback

Revert this PR. No installed state changes, so no re-run of `install-hooks` is
needed. `cli.py toggle post_ship off` stops the hook immediately.

## Deviations

- 2026-10-31: review fixes added one behaviour line to verify-and-rollback.md (stop and surface when rollback or the post-rollback check fails) and test assertions in test_post_ship_capture.py. Both came from review threads on #432.
