---
id: 0124
status: accepted
date: 2026-11-23
tier: normal
blast_radius:
  - engine/nervepack_engine/np_transcript_signals.py
  - engine/nervepack_engine/np_lesson_resolve.py
  - engine/nervepack_engine/np_capture.py
  - engine/nervepack_engine/np_turn_parse.py
  - engine/nervepack_engine/hooks/lesson_recall.py
  - engine/nervepack_engine/hooks/lesson_guard.py
  - engine/setup/np_agentic_cron.py
  - engine/setup/np-transcript-extract.py
  - engine/nervepack_engine/np_scrub.py
  - engine/setup/np_graduation_detect.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/tests/**
  - agents/np-flow-episodic-maintain.md
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - CHANGELOG.md
  - change-specs/signals-resolved-lessons.md
---

# 0124: Signal pre-pass for capture and a closed state for lessons

## Context and problem statement

Capture asks the model to find struggles in a raw transcript. It spends tokens and can
invent friction that never happened. Lessons also have no end state, so a guard keeps
firing after the issue or PR that fixed its cause has landed.

## Considered options

1. Leave the model to find struggles, and prune stale lessons by hand. Bad, because both
   problems stay.
2. A deterministic pre-pass anchors struggles, and a `resolved_by` link closes lessons.
   Good, because both checks are stdlib and fail open.

## Decision

We will run `np_transcript_signals.collect()` before the capture model and drop any
struggle without a real `file:line` anchor. We will let a lesson block carry
`resolved_by` and mark it `status: resolved` from the daily cron once the link lands.

Chosen option: 2, because it cuts invented struggles and silences fixed lessons.

## Non-goals

Reopening resolved lessons automatically. The maintain agent does that on a recurring
anchored struggle.

## Cross-cutting concerns

- Security: `gh` gets only a parsed `owner/repo/number`. Nothing else from a lesson reaches argv.
- Privacy: excerpts go through the existing capture scrub before the inbox.
- Observability: `signals{}` counts per note. The cron logs resolved topics.

## Consequences

- Good, because struggles cite real lines and fixed lessons stop firing.
- Bad, because a model that skips `anchor` loses its struggles. Param `memory.signals=off` restores the old path.
- Neutral, because the cron makes one `gh api` call per open linked block.

## Confirmation

`tests/nervepack_engine/test_np_transcript_signals.py`, `tests/episodic/test_np_capture.py`
(`TestCaptureSignals`), `tests/lessons/test_lesson_resolve.py`, the resolved cases in
`test_lesson_recall.py` and `test_lesson_guard.py`, and the sweep cases in
`test_np_episodic_maintain.py`.

## Rollback

Set `memory.signals=off` and `lessons.resolve=off`, or revert the commit.

## Deviations

- 2026-11-23: added `np-transcript-extract.py` and `np_scrub.py` to the blast radius. Security review found raw provider keys reached the capture model, and `resolved_by` accepted any owner.
