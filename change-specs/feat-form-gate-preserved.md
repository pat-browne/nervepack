---
id: 0020
status: proposed
date: 2026-08-26
tier: high
blast_radius:
  - change-specs/feat-form-gate-preserved.md
  - docs/ARCHITECTURE.md
  - engine/nervepack_engine/cli.py
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/nervepack_engine/hooks/turn_gate.py
  - engine/setup/hooks.manifest
  - engine/setup/toggles.conf
  - engine/setup/tests/nervepack_engine/test_form_gate.py
  - engine/setup/tests/nervepack_engine/test_form_gate_composition.py
  - engine/setup/tests/nervepack_engine/test_turn_gate.py
---

# 0020: durable-text form gate

## Context and problem statement

This spec is written in recovery. The feature was built in an earlier session
and reached PR #304 with no `change-specs/` entry, so `spec-guard` could never
pass. The design was never the missing part: the full architectural record lives
in the content overlay at
`docs/superpowers/specs/2026-08-19-durable-text-form-gate-design.md`, and this
spec does not restate it. What follows is the governance record the engine repo
needs, plus the deviations between that design and the code that actually
shipped.

`np-flow-concise-output` failed as an advisory gate three recorded times. The
informative failure is 2026-08-19, where the gate that should have caught the
text was enabled and running throughout. `turn_gate._check_form` works, but its
threshold of 12 per 100 words sat above the worst tracked file in the repository
(median 5.17, worst 8.26). Calibrating for zero false positives produced zero
true positives.

Lowering the threshold does not fix it. Seven semicolons in a published artifact
scored 0.31 inside a total of 1.47. No aggregate threshold catches that without
also failing clean documents. The cause is a category error: gate 2 rule 6 is
absolute, passive voice and sentence length are rate-based, and the original
design pushed both through one number, so the absolute rules were diluted into
unenforceability.

## Decision

We will split the form check into two channels and extend it from the closing
message onto text that persists.

**Channel A, categorical.** Zero tolerance on em dash, semicolon, contraction,
and marketing adjective, counted on code-stripped prose.

**Channel B, rate.** The existing aggregate, recalibrated from 12 to 2.5,
advisory through `additionalContext` only.

The hook reads the overlay linter's own violation counts and never reimplements
its regexes.

## Considered options

Recorded in full in the overlay design doc. In summary: lowering the threshold
alone cannot catch categorical violations and still sees nothing outside the
closing message. `deny` would need an amendment to ARCHITECTURE invariant 1 and
would let a linter false positive wedge a tool call. Warning on both channels is
approximately the state that already failed three times. The chosen option is
`ask` on Channel A restricted to prose paths, warn on Channel B.

## Deviations from the design doc

Three, all recorded here rather than edited into the accepted design.

1. **Channel A ships `categorical=warn`, not `ask`.** The design made the corpus
   check a precondition for enabling `ask`. That check ran, and found 579
   pre-existing categorical violations spread across nearly the whole overlay
   rather than one directory. Per the design's own words, that is the signal
   that the exemption list or the calibration is wrong, not that 579 files need
   rewriting. Shipping `ask` would fire the gate on existing committed files,
   which reproduces the failure this feature exists to fix. The toggle flips
   after that decision, not before.
2. **Observability uses `np_toggle.signal`, not a dedicated
   `~/.cache/nervepack/form-gate.log`.** The signal log is existing machinery,
   the evaluator already reads it, and it satisfies the same privacy constraint:
   the hook logs rule names and counts, never the offending text.
3. **Tests live in `engine/setup/tests/nervepack_engine/`, not
   `engine/setup/tests/formgate/`.** They sit beside the other hook tests, which
   is where the runner and every sibling hook already put them.

## Non-goals

- **Substance checking.** Gate 1 of `np-flow-concise-output` needs judgment and
  cannot be linted. Channel B routes to the skill instead of replacing it.
- **Passive voice as a gate.** It stays in Channel B permanently.
- **Rewriting text automatically.** The hook reports and asks. It never edits.
- **Engine prose quality.** Tracked in issue #228.

## Cross-cutting concerns

**Security and privacy.** The hook reads text already passing through the
session, writes no copy, and logs only rule names with counts. A log line
quoting prose would leak PII into the cache directory.

**Fail-open.** ARCHITECTURE invariant 1. The hook returns empty on a disabled
toggle, a malformed payload, a non-dict `tool_input`, an extractor exception, an
absent overlay linter, a linter timeout, and unparseable linter output. `ask` is
a permission prompt rather than a block, so invariant 1 needs no amendment. This
follows the precedent `lesson_guard` already set.

**Portability.** The exemption globs are user-supplied absolute paths, so the
list separator and the path comparison both have to hold on Windows. See
Confirmation item 12.

**Performance.** One subprocess per gated tool call, bounded by `timeout_s`. The
prose-path filter runs first and returns before any subprocess for the common
case of a code edit.

## Consequences

**Good.** The categorical rules become enforceable for the first time, and the
gate fires where the failures happen, which is durable text rather than the
closing message.

**Bad.** Every gated tool call can raise a permission prompt once Channel A
moves to `ask`. Prompt fatigue is the real risk, and it is the failure mode that
ends with the toggle off. Shipping at `warn` defers that risk without removing
it.

**Neutral.** Two channels mean two toggle params. The closing-message check
keeps working as before, with a tighter threshold.

## Confirmation

Items 1 to 11 are the design doc's own list, implemented in
`test_form_gate.py` and `test_form_gate_composition.py`. This spec adds one.

12. **A Windows absolute path survives the glob list.** `_split_globs` keeps a
    drive letter attached to its path, and `_is_exempt_path` matches a target
    against a glob written with either separator. Asserted directly against
    `ntpath` semantics so the case is covered on every platform rather than only
    in the Windows lane.

## Rollback

Set `form_gate` to `off` in `toggles.conf`. The hook returns empty before it
reads a payload, a toggle param, or a file. No uninstall, no manifest edit, no
session restart.

To roll back further, remove the five `PreToolUse` rows from
`engine/setup/hooks.manifest` and rerun `cli.py setup install-hooks`. The
`turn_gate` threshold change is independent and reverts by setting
`form_threshold` back to 12, which restores a gate that never fires.
