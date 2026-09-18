# Session journal + capture-around-/clear — design

Date: 2026-09-18
Tier: **high** (lifecycle hooks, runs before a human sees a diff)
Status: proposed

## Context

Two requests.

1. Force a `np-core-capture-learning` run when the user issues `/clear`, so learnings survive a context wipe.
2. Give every session a local, append-only tracking file. It records session goal, current hypotheses, notable struggles, and notable progress. It writes on session start and before compaction. It reads back after compaction or on resume/unarchive. It is deleted once nervepack has evaluated the session.

## Feasibility finding (changes request 1)

Claude Code exposes no hook that fires before `/clear` while context is still present. `/clear` cannot be blocked, delayed, or seen by `UserPromptSubmit`. Confirmed against current hooks docs.

- `/clear` is a built-in command, not a tool call and not a prompt. So `PreToolUse` and `UserPromptSubmit` never see it.
- `SessionStart(source=clear)` fires after the wipe.
- The only pre-wipe signal is `SessionEnd`, which fires on `/clear` under an empty matcher. Claude Code may kill a slow `SessionEnd` hook.

So request 1 cannot be "intercept and block". The context is not truly lost. The transcript persists on disk, and nervepack's SessionStart backcapture sweep already re-runs capture from a prior transcript (ARCHITECTURE invariant 12). Request 1 becomes a guarantee that a capture happens around a `/clear`, using the two mechanisms that exist.

## Decisions

- Request 2 is a standalone feature (toggle `journal`), modeled on episodic capture, not an extension of the resume pointer. Resume is a deterministic no-LLM writer. Adding an LLM authoring call would fight its design.
- Field authoring uses the cheapest adequate model (haiku via the `np_model` seam), the episodic-capture pattern.
- File shape is a literal append log. Each write appends a timestamped block carrying all four fields.
- Cleanup runs after the evaluator/backcapture drain processes the session, plus a 30-day TTL safety sweep.
- Read-back does both a SessionStart injection and a UserPromptSubmit fallback. A once-per-(session,event) receipt keeps the journal from being injected twice.
- Request 1 uses a SessionEnd fast path plus the SessionStart backcapture safety net. No second heavy capture call. Reuse the existing capture path, add `/clear` coverage, let backcapture guarantee it.

## Feature 2 — session journal

### File

Path is `~/.cache/nervepack/session-journal/<session_id>.md` (override `NP_SESSION_JOURNAL_DIR` for tests). It is uncommitted and session-scoped, matching the `~/.cache/nervepack/` inbox convention.

Each write appends this block:

```
## 2026-09-18T14:03Z · <event>
**Goal:** …
**Hypotheses:** …
**Struggles:** …
**Progress:** …
```

`<event>` is `SessionStart` or `PreCompact`.

### Writer — `journal_write` (`cli.py hook journal-write <mode>`)

- `SessionStart`, mode `seed`: seeds Goal from the first user prompt in the transcript. The other three fields read `TBD`. No model call runs when the transcript has no user turn yet.
- `PreCompact`, mode `checkpoint`: haiku reads the transcript and appends a fresh four-field block before context is lost.
- Fail-open on any error (no toggle, model failure, empty transcript, unwritable dir). It returns `""` and appends nothing. It never blocks.

### Read-back — `journal_recall` (`cli.py hook journal-recall`, SessionStart)

- Reads `payload["source"]`. Injects the journal's current content via `hookSpecificOutput.additionalContext` only when source is `compact` or `resume`. Silent on `startup` and `clear`, because clear is a deliberate wipe.
- On inject, writes a receipt at `~/.cache/nervepack/session-journal/.recall/<session_id>-<source>`.

### Read-back fallback — extend `journal_recall` on UserPromptSubmit

- Registered on UserPromptSubmit. Injects once per session only if the SessionStart receipt for a compact/resume event is absent. That covers the case where SessionStart injection did not land. It mirrors the resume-recall throttle-state pattern.

### Cleanup

- Post-evaluation: the existing SessionStart backcapture sweep, after it captures and evaluates a prior session, deletes that session's journal file.
- TTL: the same sweep deletes any journal (and stale receipt) older than 30 days. That guards sessions that were never swept.

## Feature 1 — capture around /clear

- Fast path: the existing `SessionEnd` rows (`episodic-capture session-end`, `session-flush`) already fire on `/clear`. Ensure the durable `np-core-capture-learning` path is reachable there. No new heavy model call.
- Safety net: the SessionStart backcapture sweep re-runs capture from the prior transcript. Add a guard so a session ended by `/clear` that missed its fast-path capture is swept next session. This is the real guarantee.

## Wiring (new hooks.manifest rows)

```
SessionStart||… hook journal-recall
SessionStart||… hook journal-write seed &
PreCompact||…   hook journal-write checkpoint
UserPromptSubmit||… hook journal-recall
```

`journal-recall` on SessionStart is synchronous, because it must return additionalContext. `journal-write seed` is backgrounded (`&` plus redirect per the manifest's stdout rule). The PreCompact checkpoint runs alongside the existing `episodic-capture checkpoint` row.

## Toggle

In `toggles.conf`: `journal|shared|runtime|on|model=haiku,ttl_days=30,recall_sources=compact,resume`

## Invariants

- All four new hook entry points fail open (invariant 1). None deny or ask. No new blocking hook, so no invariant-1 amendment.
- The reliable trigger is SessionStart (invariant 12). Read-back and cleanup live on SessionStart/backcapture. The SessionEnd and PreCompact writes are best-effort.
- No machine-specific absolute paths. The cache dir resolves from `HOME`, overridable by env for tests (host-portability).

## Rollback

Flip `journal` off (`cli.py toggle journal off`). Every entry point checks it and returns at once. Remove the four manifest rows and re-run `cli.py setup install-hooks`, which is idempotent. No committed data to revert. Journal files are local cache.

## Security surfaces (reviewed at Phase 6)

- The haiku call reads the raw transcript. Route it through the same scrub episodic capture uses (`np_scrub` / `pii_filter`) before persisting, so PII does not land in the journal file.
- Journal files are local, uncommitted, and confined to the user's cache dir. The CI PII guard never sees them.
- Injected additionalContext is model-facing only. No shell interpolation of journal content.

## Testing

Per-hook unit tests under `engine/setup/tests/journal/`.

- seed append: Goal comes from the first prompt, others `TBD`, no model call on an empty transcript.
- checkpoint append: four fields present, timestamped, appended not overwritten.
- read-back source-gating: compact/resume inject, startup/clear stay silent.
- receipt coordination: SessionStart inject writes a receipt, UserPromptSubmit skips when the receipt is present and injects when it is absent.
- cleanup: post-eval delete removes the swept session's file, TTL removes files older than 30 days, both leave current-session files intact.
- fail-open: model error, empty transcript, and unwritable dir each return `""` and never raise.
- F1: a `/clear`-ended session missing fast-path capture is picked up by the backcapture guard.
