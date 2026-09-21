---
id: 0037
status: accepted
date: 2026-09-18
tier: high
blast_radius:
  - engine/nervepack_engine/np_journal.py
  - engine/nervepack_engine/hooks/journal_write.py
  - engine/nervepack_engine/hooks/journal_recall.py
  - engine/nervepack_engine/hooks/backcapture_sweep.py
  - engine/nervepack_engine/cli.py
  - engine/setup/hooks.manifest
  - engine/setup/toggles.conf
  - engine/setup/tests/journal/**
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - change-specs/worktree-feat+session-journal-and-clear-capture.md
---

# 0037: Session journal + capture-around-/clear

## Context and problem statement

Two gaps exist.

- A `/clear` can wipe context before a learning is captured.
- A session has no live, human-readable record of its goal, hypotheses,
  struggles, and progress that survives a compaction.

Claude Code offers no pre-`/clear` hook, so `/clear` cannot be intercepted or
blocked. This change-spec is the governing record. A fuller design doc belongs in
the content overlay, not the engine tree.

## Considered options

1. Intercept and block `/clear` until capture runs. Bad, because no hook fires
   before `/clear` with context present.
2. Extend the resume pointer to carry the four fields. Bad, because resume is a
   deterministic no-LLM writer and an LLM authoring call fights its design.
3. Standalone `journal` feature modeled on episodic capture, plus a SessionEnd
   fast path and a SessionStart backcapture safety net. Good, because it reuses
   proven patterns and matches invariant 12.

## Decision

We will add a standalone `journal` feature. Details:

- A haiku call authors four fields into a local append log at
  `~/.cache/nervepack/session-journal/<session_id>.md`.
- It writes on SessionStart (seed) and PreCompact (checkpoint).
- It reads back on SessionStart when source is compact or resume.
- A UserPromptSubmit fallback covers a missed SessionStart injection, keyed by a
  receipt so the journal is never injected twice.
- The existing backcapture sweep deletes a session journal after evaluation, and
  age-outs any journal past 30 days.
- For `/clear`, the existing SessionEnd capture path already fires, and the
  backcapture sweep guarantees a missed capture next session.

Chosen option: "option 3", because it reuses episodic capture and backcapture
rather than inventing new machinery, and never adds a blocking hook.

## Non-goals

- Blocking or delaying `/clear`. Not possible, and not attempted.
- A second heavy capture model call on every SessionEnd. Episodic capture plus
  backcapture already cover it.

## Cross-cutting concerns

- Security: the haiku call reads the raw transcript, routed through the same
  scrub episodic capture uses before any text reaches the journal file.
- Privacy: journal files are local, uncommitted, and confined to the user cache
  dir. Read-back injects scrubbed content only.
- Observability: every entry point logs one dated bail line on early return,
  matching invariant 1.

## Consequences

- Good, because a compacted or resumed session gets its goal and progress back
  in front of the model.
- Good, because `/clear` no longer risks losing a learning.
- Neutral, because the feature adds one haiku call per PreCompact, gated by the
  toggle and skipped on an empty transcript.
- Bad, because SessionEnd and PreCompact writes are best-effort. The SessionStart
  read-back and backcapture cleanup are the reliable legs.

## Confirmation

- Unit tests under `engine/setup/tests/journal/` assert append shape, read-back
  source-gating, receipt coordination, cleanup, TTL, and fail-open.
- `cli.py toggle audit` confirms the `journal` family is wired.
- The suite runs via `bash engine/setup/tests/run-all.sh journal`.

## Rollback

- Flip the feature off with `cli.py toggle journal off`. Every entry point checks
  the toggle and returns at once.
- Remove the four `hooks.manifest` rows and re-run `cli.py setup install-hooks`,
  which is idempotent.
- No committed data to revert, because journal files are local cache.

## Deviations

<none yet>
