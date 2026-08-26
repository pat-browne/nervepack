---
id: 0020
status: proposed
date: 2026-08-26
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/turn_gate.py
  - engine/nervepack_engine/np_turn_parse.py
  - engine/setup/tests/nervepack_engine/test_turn_gate.py
  - engine/setup/tests/nervepack_engine/test_np_turn_parse.py
  - change-specs/**
---

# 0020: recognize SendUserFile and a hand-typed diff as delivered

## Context and problem statement

`turn_gate.py`'s `_check_diff` warns on a turn that changed a markdown file
without "delivering a rendered diff." It clears only when `turn.delivery`
contains the literal substring `"np-md-diff"`, which `np_turn_parse.py`'s
`_scan` appends only when a `Bash` tool_use command contains that substring,
i.e. only when `np-md-diff.py` actually ran.

`np-flow-deliver-diff`'s own table prescribes two other equally valid
deliveries: `SendUserFile` on a file the turn *created* (no base version
exists, so the whole file is the change), and a diff pasted directly into the
response text. `_scan` already records the first as `"sent a file to the
user"` and captures the second inside `turn.final_text`, but `_check_diff`
reads neither. A session that satisfied the skill correctly, repeatedly, still
got the warning every turn -- observed live today across several turns editing
`MEMORY.md` and other files, including turns where nothing was touched at all,
because `turn.edits` re-derives from a turn boundary that (see Non-goals) is a
separate, already-tracked question.

## Considered options

1. **Accept `"sent a file to the user"` unconditionally, for any md file.** —
   Good, because it is the smallest diff. Bad, because it also clears an
   *edited* file sent whole with no diff, which is exactly the workaround the
   skill's own table rules out ("Edited the file: diff first, then the file if
   it helps"). Rejected -- it would trade one false positive for a real false
   negative.
2. **Track which paths this turn's tool calls imply are newly created (`Write`)
   versus definitely pre-existing (`Edit`, which the harness only allows after
   a prior `Read`), and only clear `SendUserFile`-only delivery when every
   undelivered `.md` path is in that created set.** — Good, because it matches
   the skill's own distinction without inventing a new signal the transcript
   doesn't already carry. Bad, because `Write` on an already-existing path
   (an overwrite) is indistinguishable from a fresh create by tool name alone;
   accepted as a bounded imprecision (see Non-goals).
3. **Have `_scan` classify the hand-typed-diff case into a new delivery
   marker, mirrored by a duplicate check in `_check_diff`.** — Good, symmetric
   with the `SendUserFile` fix. Bad, forces every direct-Turn-construction unit
   test (this file's own `_turn()` helper bypasses `parse()`/`_scan`
   entirely) to fake a marker string that has no meaning outside this one
   check. Rejected in favor of option 4.
4. **Expose `np_turn_parse.has_diff_shape(text)` and have `_check_diff` call it
   directly on `turn.final_text`.** — Good, because it is the literal fix the
   bug names ("`_check_diff` never reads that field") with no indirection, and
   it is trivially unit-testable against a hand-built `Turn` with no transcript
   file involved. Chosen alongside option 2.

## Decision

We will add `Turn.created` (paths whose _last_ relevant tool call this turn was
`Write`), and widen `_check_diff` to also clear when either holds:
`np_turn_parse.has_diff_shape(turn.final_text)` is true (a `diff`-tagged fenced
block, or a fenced block containing a unified-diff line marker: `@@ ... @@`,
`--- `, or `+++ `), or `turn.delivery` contains `"sent a file to the user"` AND
every undelivered `.md` path in `turn.edits` is also in `turn.created`.

Chosen option: 2 + 4 together, because each targets exactly the delivery path
the skill already prescribes, and neither weakens the check for a genuinely
edited file that was only ever sent whole.

## Non-goals

**The turn-boundary question.** The same bug report asked whether a
`<task-notification>` or `<local-command-caveat>` message advances
`np_turn_parse.parse()`'s boundary (`_is_typed_user`: `type=="user"` AND
`promptSource=="typed"`). Investigated separately, reported in the PR
description, not touched here: both message shapes carry `promptSource` values
other than `"typed"` (`None` and `"sdk"` respectively, confirmed against real
transcripts) and correctly do not advance the boundary -- that is by-design,
not this bug. A larger, distinct finding (real transcripts show `"typed"`
prompts are rare -- `"sdk"`-entrypoint and slash-command turns essentially never
carry it, which pushes `parse()` into its documented "no typed record, scan the
whole file" fallback far more often than the fallback's own test comment
implies) is reported but not fixed here; no confident redesign was reached for
what should replace it.

**Per-path diff coverage.** `_check_diff` already clears for *every* `.md` path
in the turn the moment `"np-md-diff"` fires once, even across several edited
files. This change matches that existing coarseness rather than introducing new
precision the original check never had.

## Cross-cutting concerns

- **Security:** none. No new input crosses a trust boundary; both new checks
  read fields the module already parses from the same transcript file.
- **Privacy:** none. No new data is retained; `has_diff_shape` only pattern-matches
  text already held in `turn.final_text`.
- **Observability:** none added or removed. The gate still fails open on every
  error path (unchanged).

## Consequences

- Good, because the two most common correct deliveries no longer trip a false
  warning.
- Good, because `has_diff_shape` is a named, independently-tested primitive
  instead of logic buried inside `_check_diff`.
- Neutral, because `Write`-implies-created is a heuristic, not a certainty; an
  overwrite of a pre-existing file via `Write` (rather than `Edit`) still
  clears on a bare `SendUserFile`. Accepted: the gate is advisory (`warn` by
  default for `turn_gate.diff`), and this is strictly fewer false positives
  than before, not a new false negative class the skill didn't already permit
  in spirit.

## Confirmation

- `engine/setup/tests/nervepack_engine/test_turn_gate.py`:
  `test_send_user_file_on_created_md_is_silent` and
  `test_typed_diff_in_final_text_is_silent` fail on the pre-fix code and pass
  after; `test_send_user_file_on_edited_md_still_warns` proves the fix did not
  overshoot into option 1.
- `engine/setup/tests/nervepack_engine/test_np_turn_parse.py`:
  `test_write_tool_marks_path_as_created`,
  `test_edit_tool_does_not_mark_path_as_created`, and four
  `test_has_diff_shape_*` cases cover the new primitives directly.
- `bash engine/setup/tests/run-all.sh` run clean.

## Rollback

1. Revert this commit. `_check_diff` returns to accepting only
  `"ran np-md-diff"`, which is its current (over-narrow but safe) behavior.
2. No data or state migration is involved -- the change is pure control flow
  inside a fail-open Stop hook, so a revert has no cleanup step.
