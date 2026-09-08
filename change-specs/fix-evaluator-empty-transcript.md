---
id: 0028
status: proposed
date: 2026-09-08
tier: normal
blast_radius:
  - engine/nervepack_engine/np_evaluator.py
  - engine/setup/tests/evaluator/**
  - change-specs/**
---

# 0028: The evaluator must not score an empty transcript

## Context and problem statement

`np-transcript-extract.py` states its contract in its own docstring: "any
read/parse error -> empty stdout, exit 0 (the caller bails cleanly)". Its
caller, `np_evaluator.evaluate()`, never checks the result. An empty
extraction goes straight into `np_model.complete()`, the judge replies asking
for a session log, and that reply is stored as a real record with
`contribution_score: 0`.

This is not rare. The SessionEnd evaluator is best-effort by design (invariant
12) and can fire against a transcript that is absent or not yet flushed. As of
2026-09-08, 224 of 1592 committed metrics records are this artifact — 14% of
the series, all scoring 0, all carrying a junk suggestion. They drag the
dashboard average down and fill the suggestions queue, and each one costs a
model call that could never produce a verdict.

## Considered options

1. Bail before the model call when the extraction is empty — Good, because it
   honours the extractor's stated contract at the one place that breaks it.
   Good, because it removes the model call rather than filtering its output.
   Neutral, because it makes an already-silent failure silent in a new way.
2. Filter the junk at aggregation time — Bad, because the model call is still
   paid for, and the filter has to pattern-match free-form judge prose.
3. Make the extractor fail closed (non-zero exit) — Bad, because every other
   caller relies on the fail-open contract; this widens the blast radius to
   the episodic pipeline for no gain here.

## Decision

We will return early from `evaluate()` when the extracted conversation is
empty or whitespace, logging a bail line naming the transcript path.

Chosen option: "Bail before the model call", because the defect is a caller
ignoring a documented contract, and the fix belongs at that caller.

## Non-goals

Purging the 224 existing records from `dashboard/data/metrics.jsonl`. That is
a data question with its own retention and provenance trade-offs, and it is
tracked separately.

Adding a minimum-length threshold. Only the empty case is a contract
violation; a short-but-real session is still a session.

## Cross-cutting concerns

- Security: none — the guard reduces what reaches the model.
- Privacy: the bail line records a transcript path, matching the other bail
  lines already written to the same log.
- Observability: the bail is logged to `EVAL_JUDGE_LOG`, so a run that scores
  nothing stays distinguishable from a run that never started.

## Consequences

- Good, because the metrics series stops accruing 0-score artifacts.
- Good, because a wasted model call per degenerate SessionEnd is removed.
- Neutral, because sessions that genuinely have no transcript now produce no
  record at all rather than a misleading one.

## Confirmation

`engine/setup/tests/evaluator/test_np_evaluator.py`
`test_6_empty_transcript_extraction_bails_before_the_judge` asserts that a
missing transcript path calls no model, writes no inbox record, and logs a
bail.
