---
id: 0102
status: accepted
date: 2026-10-29
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/lesson_recall.py
  - engine/nervepack_engine/hooks/lesson_guard.py
  - engine/nervepack_engine/np_capture.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/tests/nervepack_engine/test_lesson_recall.py
  - engine/setup/tests/episodic/test_np_capture.py
  - skills/np-flow-speed/SKILL.md
  - docs/FEATURES.md
  - change-specs/feat-memory-guard-recall-gate.md
---

# 0102: Memory write guard and lesson recall gate

## Context and problem statement

Lesson recall matched triggers as substrings. On live data (312 topics) an unrelated
prompt injected 17 lessons, because `ci` matches "decision" and `eval` matches
"evaluate". Capture wrote every model-extracted struggle and strategy to the inbox
with no check for junk or repeats, so distillation spent tokens on noise.

## Considered options

1. Require two trigger hits per topic. Bad: on four sample prompts it blocked every
   lesson, including the relevant `ci-job-timeouts`.
2. Require one rare trigger (low document frequency). Bad: it also blocked
   `ci-job-timeouts`, since `ci` is shared by 6 topics.
3. Whole-word match, rank by hits then trigger rarity, cap at the top 3. Good: the
   unrelated prompt drops from 17 to at most 3, and relevant topics still rank first.
4. An LLM write filter. Bad: a model call per capture, against deterministic-first.

## Decision

Chosen option: 3 for recall, plus a deterministic write guard in
`np_capture.append_note()`: drop junk, too-short, too-long and duplicate items, and
record each drop in `guard.dropped`. Both are params (`lessons.recall_top`,
`lessons.recall_min_hits`, `memory.write_guard`).

## Non-goals

- Episodic recall. `np_episodic_match` already matches whole words and caps at 3.
- The MCP server's `_tool_recall`. Revisit if its matches prove noisy.
- Hebbian decay. Evaluated below and deferred.

## Hebbian decay evaluation

Data: 436 lesson blocks on overlay `origin/main`. 226 (52%) have `seen: 1`. 87 were
last updated before 2026-08-01, and 55 of those were seen once. Usage signal: 1363
evaluator records name a specific lesson in `assets_used` about 30 times, across 8
lessons. Recall fires one marker per hook, not per topic.

Verdict: defer. Decay needs a per-lesson "fired and helped" signal, and none exists.
Strengthening on `seen` alone would reward capture frequency, not usefulness. Trigger to
revisit: recall logs the injected topic names, and 30 days of that data exist.

## Cross-cutting concerns

- Security: no new input surface. The guard runs before the existing scrub.
- Privacy: `guard.dropped` keeps the first 80 characters of a dropped item. That text
  passes the same scrub as the rest of the record.
- Observability: `guard.dropped` in each inbox record.

## Consequences

- Good: fewer, more relevant lesson injections per prompt.
- Bad: a trigger no longer matches inside a longer word or an inflection (`merge` misses "merging"). Maintain can add inflected triggers where recall drops.
- Neutral: the guard reads the whole inbox per write. It is drained daily, so it stays small.

## Confirmation

`test_lesson_recall.py` (`test_recall_gate_*`, 3 tests that fail on the old code) and
`test_np_capture.py` (`test_guard_*`, 3 tests).

## Rollback

Set `lessons.recall_top` to a large number and `memory.write_guard=off` with
`cli.py toggle param`. For a full rollback, revert the squash commit. No data migration.
