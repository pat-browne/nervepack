---
name: np-kb-evaluator-signals
description: Reference for every deterministic field in the nervepack evaluator signals record — what populates it, when it's reliably non-zero, and its known zero-biases. Use when auditing the metrics pipeline, debugging a suspicious field, extending signals, or explaining why a dashboard panel shows zero.
---

# Evaluator signals — field catalog and zero-bias audit

The performance evaluator (`engine/setup/np-evaluator.sh`) writes one JSON record per session
into `~/.cache/nervepack/evaluator-inbox/`, which `73-aggregate-metrics.sh` drains into
`dashboard/data/metrics.jsonl`. Every record has a `signals` object produced **deterministically**
by `engine/setup/np-eval-signals.py` — no LLM, no guessing — plus LLM-derived fields from Haiku.

## Deterministic signals (`signals{}`)

### `skills_invoked` (array of strings)
- **Source**: `parse_transcript()` — regex `"skill":"([^"]+)"` across every JSONL line of the transcript.
- **Populated when**: Claude used the Skill tool at least once during the session.
- **Zero bias**: Legitimately empty if no skills were invoked. Not a pipeline gap.
- **Status**: LIVE ✓

### `playbook_fires` (int)
- **Source**: `count_markers()` — counts `lesson-guard` prefixed lines in `~/.cache/nervepack/session-signals/<sid>.log`, written by `engine/setup/lesson-guard.sh` when a Bash command matches a lesson's enforce `tool_match` pattern.
- **Populated when**: An imminent Bash command matches an entry in `playbooks/INDEX.md`.
- **Zero bias**: **Genuinely sparse today.** Only two playbooks currently exist (`bash-nested-substitution`, `mv3-screenshot-capture`). As the catalog grows, this rises naturally. Not a dead signal.
- **Status**: LIVE ✓ — sparseness reflects catalog size, not a wiring gap.

### `playbook_heeded` (int)
- **Source**: `gated_fingerprints(log_path) - exec_fps` — fingerprints of gated commands from the signal log that never appeared as executed Bash tool calls in the transcript.
- **Populated when**: A playbook guard fired AND the session did not subsequently run that exact command. A heeded count of 1 means the intervention worked.
- **Zero bias**: Inherits `playbook_fires` sparseness. Also 0 if all gated commands were run anyway (guard noted but ignored).
- **Status**: LIVE ✓

### `recall_injections` (int)
- **Source**: `count_markers()` — sum of `playbook-recall`, `episodic-recall`, and `strategy-recall` prefixed lines in the session-signals log (each recall hook writes one marker via `np_signal`).
- **Populated when**: A recall hook matched the prompt and injected context in the first N prompts of a **live** session.
- **Zero bias**: **Structural zero for back-captured sessions.** The signal log lives in `~/.cache/nervepack/session-signals/` and is written by live hooks at runtime; the back-capture sweep re-runs the evaluator against the old transcript, but the ephemeral signal log for that old session no longer exists. So `recall_injections` is always 0 in back-captured records, even when recall hooks did fire during that original session.
- **Status**: LIVE for live sessions; structural 0 for back-captures. Not fixable without logging recall events to a durable transcript artifact.

### `directive_present` (bool)
- **Source**: Shells out to `bash -c 'source np-toggle-lib.sh; np_enabled directive'`.
- **Populated when**: Always — reflects the `directive` toggle state at evaluation time.
- **Status**: LIVE ✓ (currently always `true` unless the directive toggle is explicitly disabled).

### `directive_tokens` (int)
- **Source**: `len(open("nervepack-session-directive.md").read()) // 4` — rough fixed token cost of the SessionStart context injection (~876 tokens at current size).
- **Populated when**: Always. Fixed at evaluation time, not session time.
- **Status**: LIVE ✓

### `struggles` (int)
- **Source**: `episodic_struggles(sid)` — reads all `.jsonl` files in `~/.cache/nervepack/episodic-inbox/`, matches by `session_id`, counts `struggles[]` array length, takes the max across duplicate captures (a PreCompact checkpoint + the session-end capture may both exist).
- **Populated when**: `episodic-capture.sh` ran for this session AND the Haiku summarizer detected real failures/corrections in the transcript (returning a non-empty `struggles[]`).
- **Zero bias**: Often 0 for two reasons: (a) **SessionEnd is unreliable** — Claude Code kills slow `claude -p` hooks before they complete, so the episodic capture that populates `struggles` may not fire; the `np-backcapture-sweep.sh` re-runs both capture and evaluator but this still requires a successful capture pass. (b) **Sessions with clean execution** legitimately return 0. This was once flagged as "hardcoded to 0" in a code review, but the code does correctly read from the inbox — the zero-bias is a capture-pipeline limitation, not dead code.
- **Status**: LIVE ✓ — verify by checking whether `~/.cache/nervepack/episodic-inbox/` has a matching record for the session.

### `tool_calls` (int)
- **Source**: `parse_transcript()` — counts every line containing `"tool_use"` in the transcript JSONL.
- **Populated when**: Any tool (Bash, Read, Grep, Skill, etc.) was called during the session.
- **Zero bias**: 0 for pure-text automation runs (cron agent sessions, episodic-maintain, etc.) that generate no tool calls.
- **Status**: LIVE ✓

### `tokens` (object)
Keys: `input`, `output`, `cache_read`, `cache_creation`, `total`.
- **Source**: `parse_transcript()` — parses `usage` blocks from assistant messages, **deduped by message id** (Claude Code logs one JSONL line per content block of a turn, all sharing the same id and usage object; without dedup, cache_read inflates to millions).
- **Populated when**: Any assistant turn with a `usage` block exists.
- **Zero bias**: Near-zero for cron/automation sessions. `cache_read` is typically the largest field for real interactive sessions (prompt caching is heavily used).
- **Status**: LIVE ✓

## LLM-derived fields (Haiku verdict, via `np-evaluator.sh`)

These are not in `signals{}` but sit at the record's top level:

| Field | Type | Notes |
|---|---|---|
| `contribution_score` | int 0–100 | Haiku's holistic judgment of how much nervepack helped |
| `helped` | string[] | Bullet points of what the pack contributed |
| `shortfalls` | string[] | Where the pack missed or was stale |
| `suggestions` | object[] | `{text, confidence, target, auto_safe}` — actionable improvements |
| `assets_used` | object[] | `{asset, kind, used}` — which skills/hooks were used |

A deterministic cost-aware suggestion is also appended by the evaluator shell: if `tokens.output >= evaluator.cost_hi_tokens` (default 200k) AND `contribution_score <= evaluator.score_lo` (default 40), a "High token cost" suggestion is injected regardless of Haiku output.

## Auditing signal health

Bash commands to verify real vs structural zeros: references/auditing-signals.md

## Adding a new signal

Five-step procedure (extractor → record → ARCHITECTURE → test → marker): references/adding-a-signal.md

## Known limitations (not bugs)

- `recall_injections` cannot be reconstructed for back-captured sessions — the signal log is ephemeral. If this matters, the fix is to write recall events into the transcript somehow (a `[nervepack-recall]` assistant turn), but this has blast-radius implications.
- `struggles` is only as reliable as the episodic capture pipeline. Improve capture reliability via the back-capture sweep — if the sweep re-runs capture for every session, struggles will be populated even for sessions where SessionEnd didn't fire.
- Signals are per-session, not per-project. There's no aggregation across sessions today; `dashboard/build.py` passes the raw records through and `index.html` aggregates client-side.
