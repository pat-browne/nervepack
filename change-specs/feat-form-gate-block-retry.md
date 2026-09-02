---
id: 0023
status: proposed
date: 2026-09-02
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/nervepack_engine/np_capture.py
  - engine/setup/toggles.conf
  - engine/setup/tests/nervepack_engine/test_form_gate.py
  - docs/ARCHITECTURE.md
  - change-specs/feat-form-gate-block-retry.md
---

# 0023: form_gate gets a block-retry-escalate mode

## Context and problem statement

`form_gate.categorical` today has three states -- `ask`, `warn`, `off` -- and
none of them stop a write. `ask` is a permission prompt the reader can accept
without changing anything. `warn` only attaches context. A maintainer who
wants the zero-tolerance rules (no em dash, no semicolon, no marketing
adjective, and the two length rules) to actually hold has no way to make a
violating write fail outright.

A hard block that never yields is its own problem. The linter is a
heuristic, and a rule that cannot be satisfied after a genuine rewrite
attempt should surface for tuning rather than lock the session out of
writing the file at all.

## Considered options

1. **A hard block with no escape hatch.** Good, because it is the simplest
   rule to state. Bad, because a miscalibrated rule (a false positive in
   `long_sentence`, say) would wedge a session with no way to make progress on
   that file short of turning the whole feature off. Rejected.
2. **A hard block that always escalates to `ask` on the very first hit.**
   Good, because it never wedges. Bad, because it gives up the point of
   blocking. A single retry nudge often fixes an easy violation, and asking
   immediately reproduces today's `ask` behavior with extra steps. Rejected.
3. **Deny for the first two hits per (session, target), escalate to `ask` on
   the third, and record the escalation as a struggle for the lessons
   pipeline.** Good, because a real rewrite gets two tries before the gate
   backs off, and a rule that will not settle leaves a trace someone will
   actually see (episodic-maintain distills struggles into
   `memory/lessons/`). Neutral, because it needs a small per-target counter,
   which is new state to fail open around. Chosen.

## Decision

`form_gate.categorical` gains a fourth value, `block`, alongside `ask` /
`warn` / `off`. The engine default in `toggles.conf` stays `warn`.

`block` mode has its own violation set, narrower than the `ask`/`warn` set:
`em_dash`, `semicolon`, `marketing_adjective`, `long_sentence` (>20 words),
`long_paragraph` (>6 sentences). `contraction` is left out on purpose. It
fires often enough in ordinary prose that hard-blocking it would make the
mode unusable, so it stays a rate-channel signal only, exactly as it already
is for that channel.

A write carrying at least one of those violations is keyed by a hash of
`session_id` + a target (the file path for `Write`/`Edit`/a file-backed
`Artifact`, otherwise the MCP/tool label already used for extraction). A
counter for that key lives under `~/.cache/nervepack/form-gate-retry/`:

- counter `< 2`: deny, naming the violations, and increment the counter.
- counter `>= 2`: reset the counter, return `ask` (not a further block) whose
  reason says the rule may need tuning and points at `np-ste-lint.py` and
  `np-flow-concise-output`, signal `form-gate-escalation :: <label> ::
  <violations>`, and append a `struggles[]` record to the episodic inbox.
- a write that lints clean for that target clears its counter.

The struggle record reuses `np_capture.append_note`, the JSONL-line-plus-
scrub write `np_capture.capture()` already performs for its own note, now
pulled out into its own function so both callers share one write path rather
than each hand-rolling the JSON.

`ask` / `warn` / `off` behavior is unchanged. Same violation set (still
including `contraction`), same messages, same rate channel.

## Non-goals

- Changing the engine default. `categorical` still ships `warn`. `block` is
  something a maintainer opts into in their own content overlay, the same way
  `ask` already is.
- Making the retry limit (2) or the blocking violation set configurable via a
  toggle param. Both are fixed in code for this change. A param can follow if
  a real need for tuning them shows up.
- Touching the linter itself. `long_sentence` and `long_paragraph` are
  existing report keys. This change only reads them.

## Cross-cutting concerns

- **Security:** the retry-counter files hold nothing but an integer count,
  keyed by a one-way hash of session id + target. No new secret-bearing data
  is written anywhere.
- **Privacy:** the struggle record's `cwd`/`project` fields mirror exactly
  what `np_capture.capture()` already writes into the same inbox for every
  session, so nothing new is exposed. `np_scrub.scrub` still runs over the
  line before it lands on disk.
- **Observability:** the escalation path calls `np_toggle.signal`, so it shows
  up in the session signal log the same way every other `form_gate` decision
  already does.

## Consequences

- Good, because a maintainer who wants the categorical rules to actually hold
  now has a way to make that true, without giving up an escape hatch for a
  rule that turns out to be miscalibrated.
- Good, because the escalation path feeds the same lessons pipeline that
  already distills other struggles, so a rule that will not settle becomes
  visible instead of silently eating retries forever.
- Bad, because `block` adds a second piece of on-disk state to `form_gate`
  (parts of `~/.cache/nervepack/`), which is one more thing a corrupt-cache
  bug report could point at. Mitigated by fail-open reads, where a corrupt
  counter file reads as 0, not an error.
- Neutral, because a forker who never sets `categorical=block` sees no
  behavior change at all.

## Confirmation

- `engine/setup/tests/nervepack_engine/test_form_gate.py` asserts: a deny
  under the retry budget, escalation to `ask` at counter `== 2` together with
  a struggle append, the counter clearing after a clean pass, fail-open when
  the counter file is corrupt, `contraction` alone not blocking,
  `long_sentence` and `long_paragraph` each blocking on their own, and
  `ask` / `warn` / `off` unchanged.
- `bash engine/setup/tests/run-all.sh` passes, aside from the pre-existing,
  unrelated `test_dashboard_lifecycle.py` failure already present on `main`.

## Rollback

To disable without reverting code, in `~/.config/nervepack/toggles.local`:

```
form_gate.categorical=off
```

or, to fall back to the pre-existing non-blocking behavior instead of
disabling the gate outright:

```
form_gate.categorical=warn
```

or to turn the whole hook off:

```
form_gate=off
```

To revert the code, `git revert` the merge commit. No hook registration
change is needed. `form_gate` is already registered on the six PreToolUse
matchers, so no `install-hooks` re-run is required.

## Deviations

(none yet)
