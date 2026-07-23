---
name: np-core-suggestions-review
description: Triage the nervepack performance dashboard's accumulated evaluator suggestions — rank the open ones, decide which to implement (with reasoning), then clear the slate so new suggestions accumulate fresh. Use when the user says "review nervepack suggestions", "evaluate the evaluator/dashboard suggestions", "which suggestions should we build", "clear the suggestions", "/np-suggestions", or after a stretch of sessions when the Suggestions panel has filled up. Tool-agnostic: works from any host (Claude Code, Goose, a terminal); the dashboard's served-mode buttons are the GUI shortcut for the same flow.
---

# Reviewing nervepack evaluator suggestions

The performance evaluator appends `suggestions[]` to every session's metrics record.
They pile up in `dashboard/data/metrics.jsonl` and surface on the dashboard's
Suggestions panel. This skill turns "look at the pile, decide what's worth building,
wipe it" into a repeatable loop. The deterministic ranking/clearing is a script; the
*judgment* (which to implement) is yours.

## The engine (deterministic, no model)

`engine/setup/np-suggestions-review.py` — reuses the dashboard's own normalization so its
view of "open" matches what the dashboard shows.

- **List** the open, deduped, confidence-ranked suggestions:
  ```bash
  python3 ~/Code/nervepack/engine/setup/np-suggestions-review.py list --top 10
  python3 ~/Code/nervepack/engine/setup/np-suggestions-review.py list --json   # for machine use
  ```
  "Open" = present in metrics.jsonl AND not already in
  `dashboard/data/resolved-suggestions.txt`. Dedup is by normalized text, keeping the
  max confidence and an occurrence `count` (recurrence signal).
- **Clear** — resolve every open suggestion (default ALL) so the panel resets and new
  ones accumulate; rebuilds `metrics.js` so the dashboard reflects it immediately:
  ```bash
  python3 ~/Code/nervepack/engine/setup/np-suggestions-review.py clear
  ```
  Clearing is non-destructive: it appends the texts to the resolved ledger (the
  metrics records are untouched), so the audit trail survives.

## The workflow (what to actually do)

1. **List** the top-N (default 10) open suggestions.
2. **Evaluate each** with a one-line verdict — **implement** or **skip** — and a brief
   reason. Judge on: is it real and still true? is it actionable and in-scope for
   nervepack? does it duplicate an existing skill/feature? what's the cost/benefit?
   Prefer `auto_safe` + recurring (`×N`) + high-confidence items. Cross-check against
   `docs/ARCHITECTURE.md` (don't recommend something already built) and `docs/ROADMAP.md`
   (something deliberately deferred should stay deferred unless its trigger fired).
3. **Present** the verdicts to the user — a short table: rank · confidence · target ·
   verdict · reason. Call out the few worth doing now.
4. **On the user's approval, clear** — run `… clear` to reset the slate (the user
   chose "clear all reviewed"; implemented items become real work tracked elsewhere,
   the rest are dismissed). Never clear without confirmation.
5. Optionally, turn an approved "implement" item into actual work (a plan, a commit)
   or fold a durable decision into a skill via [[np-core-contribute]].

## The GUI shortcut (served dashboard)

When `evaluator.dashboard_serve` is **on** (a param, default on — flip off with
`nervepack-toggle evaluator.dashboard_serve off`), the dashboard is served from a
local backend (`engine/setup/np-dashboard-server.py`) and its Suggestions panel gains
buttons: **Resolve** (one item → `np_suggestion_resolve.py` (`cli.py suggestion-resolve`)), **Review** (a single
Haiku verdict pass over the top-N, via `np-llm.sh`), and **Review & clear** (resolve
all open). Same engine underneath — the buttons just call `/api/resolve|review|clear`.

## Notes

- The ranking script makes **no** model call (harness language policy). The only model
  use is the GUI **Review** button's single cheap Haiku classify pass, and it degrades
  gracefully (shows the ranking with no verdicts) if the seam is unavailable.
- "Clear" defaults to ALL open; pass `--top N` to clear only the top-N.
- Touches the evaluator/dashboard feature — see `docs/ARCHITECTURE.md` "Dashboard" row.
