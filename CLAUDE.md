@AGENTS.md

# nervepack — Claude Code specifics

`CLAUDE.md` is auto-loaded by Claude Code when a session starts in this directory; it
imports the tool-neutral manual above (`@AGENTS.md`) and adds the Claude-Code wiring
below. Other hosts read `AGENTS.md` directly (Cursor/Codex/Gemini/Aider/…) — see
`README.md` › Host compatibility.

Read `docs/ROADMAP.md` and re-evaluate any deferred item whose trigger now applies.
**Before changing any code, also read `docs/ARCHITECTURE.md`.**

## When the user lands in `~/Code/nervepack` and starts a session
- A `SessionStart` hook (installed via `engine/setup/50-install-session-hook.sh`)
  has already run the defensive sync in the background. Result is in
  `~/.cache/np-core-sync-status`.
- You don't need to re-pull unless the user asks.

## Why every session is told to consult nervepack first
A second `SessionStart` hook (installed via
`engine/setup/51-install-nervepack-directive-hook.sh`) runs `engine/setup/nervepack-session-directive.sh`
**synchronously** and injects `engine/setup/nervepack-session-directive.md` as session
context. This is nervepack's forcing function: skill *descriptions* load passively,
but a passive list does not get used — sessions otherwise ignore nervepack's domain
knowledge and fall back to whatever process tooling is present. The directive states
nervepack's own process expectations (explore → test-first → root-cause debug → plan)
and supplies the WHAT (domain defaults), gives a trigger→skill routing table, and tells
the session to invoke the relevant nervepack skill before working from first
principles. When you add a domain skill whose triggers are high-frequency, add a row
to that routing table so future sessions reach for it.

## Memory-store promotion (local-only)
A user cron entry (installed by `engine/setup/70-install-memory-cron.sh`) runs
`agents/np-flow-memory-promote.md` daily at 08:00 local (idempotent — a no-op when
the memory store has nothing new to promote). It triages
`~/.claude/projects/<your-project>/memory/`, promotes durable entries into
the right skill here, and commits + pushes. Logs land in
`~/.cache/nervepack/memory-promote.log`.

Cloud agents can't reach the local memory store, so this *has* to be a
local cron. Don't try to schedule it as a remote routine — it will
silently no-op because the memory dir won't exist in the cloud sandbox.

## Claude-Code hook / cron wiring details

### Episodic layer (wiring)

- **Capture** (local): `SessionEnd` + `PreCompact` hooks
  (`engine/setup/episodic-capture.sh`, registered by `engine/setup/52-install-episodic-hooks.sh`)
  summarize the session via Haiku and append a note to
  `~/.cache/nervepack/episodic-inbox/` — local only, never committed in the hot path.
  The `SessionEnd` capture is **best-effort only** — Claude Code kills slow
  SessionEnd `claude -p` hooks and `/exit` doesn't fire SessionEnd at all, so the
  reliable trigger is the back-capture sweep below.
- **Maintain** (local cron, daily 08:30): `agents/np-flow-episodic-maintain.md` drains the
  inbox into `episodic/<topic>.md`, compacts oversized themes, regenerates
  `episodic/INDEX.md`, and **auto-commits + pushes**. This is the *only* subtree
  exempt from the human-reviewed-diff gate — accepted deliberately because the
  layer is second-class and bounded. Everything else keeps the gate.
- **Recall**: `engine/setup/episodic-recall.sh` (`UserPromptSubmit`) injects matching
  themes on a session's first prompts; the [[np-core-recall]] skill pulls on demand.

### Back-capture sweep (the reliable capture trigger)

Claude Code does **not** run slow `SessionEnd` `claude -p` hooks to completion (it
exits without awaiting them) and **`/exit` doesn't fire `SessionEnd` at all** — so
the SessionEnd capture + evaluator are best-effort and, on their own, lose almost
every session. `engine/setup/np-backcapture-sweep.sh` (registered on `SessionStart`,
backgrounded, by `engine/setup/56-install-backcapture-hook.sh`; toggle `memory.backcapture`)
is the guaranteed path: it scans `~/.claude/projects/*/*.jsonl`, and for each
**completed** prior session with no record yet, re-runs the same capture + evaluator
against the saved transcript. SessionStart is awaited and the backgrounded work
survives because the parent session stays alive. Idempotent (per-`session_id` claim
marker + dedup vs committed `metrics.jsonl`), bounded (`backcapture_days`/`_max`
params), skips `agent-*` subagent transcripts and the active session, fail-open.
Promotion to the committed layers still rides the on-exit flush + daily/weekly crons
(the awaited triggers). See [[np-kb-claude-headless-scripting]] §8, ARCHITECTURE
invariant 12.

### Playbook layer (wiring)

- **Capture:** `engine/setup/episodic-capture.sh` emits `struggles[]` on sessions that
  had real failures/corrections.
- **Distill:** `agents/np-flow-episodic-maintain.md` clusters struggles into
  `playbooks/<topic>.md` with an `enforce` block and regenerates `playbooks/INDEX.md`.
- **Enforce:** `engine/setup/lesson-guard.sh` (`PreToolUse` matcher `Bash`, installed by
  `engine/setup/53-install-lesson-hooks.sh`) gates `ask` playbooks and injects `warn`
  ones at the tool call; `engine/setup/lesson-recall.sh` (`UserPromptSubmit`, merged with
  the former `strategy-recall.sh`) injects topic-matched playbooks with imperative framing.
- **Graduate:** a proven playbook is promoted to a `skills/np-kb-*` rule via the
  human-reviewed `np-core-contribute` gate, then marked `promoted`/archived.

### Feature toggles (wiring)

`sync` runs primarily on session exit (`SessionEnd`); the `SessionStart` sync is
a throttled backup governed by `sync.interval` (default 86400s = 1 day), set via
`nervepack-toggle param sync.interval <seconds>`.

Dashboard params are the worked examples for the param pattern: `dashboard_serve`
(local-server mode, default **on**) and `dashboard_open` (SessionStart auto-open,
default **on**) — both flip off per-machine with
`nervepack-toggle evaluator.<param> off`. These live in `settings.json` and
`~/.claude/projects/` only on the local machine.

### Performance evaluator (wiring)

At `SessionEnd`, `engine/setup/np-evaluator.sh` (toggle `evaluator.judge`) scores how much
Nervepack helped: deterministic signals (`np-eval-signals.py`, fed by fire-time
markers the hooks append to `~/.cache/nervepack/session-signals/`, toggle
`evaluator.signals`) + a Haiku verdict (score, helped, shortfalls, suggestions with
confidence/auto_safe, assets_used). Records land in a local inbox; the **daily**
`engine/setup/73-aggregate-metrics.sh` (toggle `evaluator.aggregate`) drains them into
committed `dashboard/data/metrics.jsonl`. All under the `evaluator` toggle family;
all fail-open. The dashboard (P2) and **suggestion implement/reject (P3)** —
per-row Implement (async agentic job via `np-implement-suggestion.sh`, `pr`/`direct`
mode) and Reject — consume this record. See
`docs/superpowers/specs/2026-06-08-suggestion-implement-reject-design.md`.

### Skill maintenance (wiring)

`engine/setup/75-skill-maintain.sh` (daily cron, 09:15) keeps skill bodies within budget,
deterministic-first. A detector (`engine/setup/np-skill-budget.py`, no LLM) flags any
`SKILL.md` over the hard `split_kb` (default 8 KB); only then does a Sonnet
`claude -p` pass (`agents/np-flow-skill-maintain.md`) move overflow detail into
`skills/<name>/references/`, leaving the decision in the body. A deterministic gate
(`engine/setup/np-skill-validate.py`) then enforces: body now under budget, frontmatter
`name`+`description` unchanged, no `[[link]]` dropped, `references/` non-empty.
Pass → commit (+push); fail → revert, skill left untouched. Idempotent; capped at
`skills.max_per_run` (2) per run. The detector also flags when the always-loaded
catalog crosses `skills.catalog_tok` (4000 tok). All thresholds are tunable toggle
params (`skills.split_kb`/`soft_kb`/`catalog_tok`/`max_per_run`; also
`memory.cap_bytes`, `evaluator.cap_bytes`). Spec:
`docs/superpowers/specs/2026-06-05-skill-maintenance-routine-design.md`.
