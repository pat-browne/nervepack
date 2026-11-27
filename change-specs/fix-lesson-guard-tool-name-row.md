---
id: 0113
status: accepted
date: 2026-11-10
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/lesson_guard.py
  - engine/setup/tests/nervepack_engine/test_lesson_guard.py
  - agents/np-flow-episodic-maintain.md
  - change-specs/fix-lesson-guard-tool-name-row.md
---

# 0113: A bare tool name never gates Bash

## Context and problem statement

The regenerated lessons INDEX put the `Read` tool name in the Bash `tool_match`
column for `security-review-skill-first`. Phase 1 reads that cell as a regex
over the command. So every Bash command containing "Read" asked for approval,
including routine heredocs.

## Considered options

1. Fix the content row only. Bad, because the weekly regeneration can write it back.
2. Skip a bare tool name in Phase 1, and tell the regenerating agent where the
   cell comes from. Good, because a bad row can no longer gate Bash.

## Decision

We will take option 2. Phase 1 skips a row only when its `tool_match` equals
the lesson's own `enforce.tool_name_match`. That proves the cell is misplaced.

The skip logs a `lesson-skip` signal, outside the `lesson-guard` prefix that
counts fires. `np-flow-episodic-maintain` step 5 says the cell comes from
`enforce.tool_match` only. Phase 2 is unchanged.

## Consequences

A real one-word Bash pattern still fires, since its lesson has no matching
`tool_name_match`. Tests 17 to 19 cover the report, the proof rule and that case.

## Rollback

Revert the squash commit. The content row fix (nervepack-content 4a62c5af)
stands on its own, so a revert brings back only the regeneration risk.
