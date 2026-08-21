---
name: np-core-sync
description: Sync ~/Code/nervepack with origin/main using strict-safe semantics (fast-forward only; never auto-rebase or autostash). Use when the user says "sync nervepack", "pull nervepack", "what's new in nervepack", when starting work after a known cron run, or when the SessionStart status file reports anything other than "up to date".
---

# np-core-sync

## Behavior contract

The underlying command (`cli.py sync`, engine/nervepack_engine/np_sync.py) is intentionally
*defensive*: it never modifies a dirty working tree, never autostashes, and
never rebases — for the engine AND for every content layer it touches. Every
run produces one of five ENGINE outcomes, written to `~/.cache/np-core-sync-status`:

| Outcome | Meaning | What this skill does |
|---|---|---|
| `up to date` | local == origin/main | report and stop |
| `fast-forwarded N commit(s)` | safe pull happened | report what changed |
| `local is N ahead of origin/main` | unpushed local commits | offer to open a PR (see below) |
| `SKIPPED (dirty)` | uncommitted edits block sync | surface diff, suggest commit/stash |
| `DIVERGED` | local and remote both have unique commits | surface both sides, ask user how to resolve |

The personal content overlay and team layers get the same ff-only treatment,
and every sync validates each layer's `.nervepack/layout.json` manifest —
full semantics (the `sync.content` gate, layer-note wording, the corrupt-manifest
warning) in `references/behavior-details.md`.

The `SessionStart` hook runs the script silently in the background — no model
in the loop, so it can never push or open a PR. This skill's interactive steps
are the only place that ever happens.

## When to invoke

- Explicit: user says "sync nervepack", "pull nervepack", "update my AI context"
- Reactive: the status file's last line is not "up to date"
- Pre-write: before [[np-core-contribute]] commits, to avoid creating a fork

## Steps

1. **Read the status file first** — cheaper than running the script and
   tells you exactly what the background hook just did:
   ```bash
   cat ~/.cache/np-core-sync-status 2>/dev/null || echo "no status yet"
   ```

2. **Run the sync in exit mode** (idempotent, writes a fresh status):
   ```bash
   python3 ~/Code/nervepack/engine/nervepack_engine/cli.py sync exit --verbose
   ```
   Bare `cli.py sync` (no `exit`) is backup mode: it throttles to `sync.interval`
   (default 86400s) and no-ops inside that window. It prints a `within Ns
   interval, skipping (backup)` line to stdout and leaves the status file's
   prior outcome in place, even when the repo has diverged since that outcome
   was written. Backup mode exists to keep the automatic `SessionStart` hook
   cheap, not for this skill's own interactive steps. `sync exit` always runs
   the real check, so use it here.

3. **Branch on the outcome.** Full per-outcome steps live in
   `references/outcomes.md`; quick summary:
   - `up to date` → report and stop.
   - `fast-forwarded N commit(s)` → show what landed (`git log <prev>..HEAD --oneline`); no further action.
   - `local is N ahead` → never push straight to main; branch, push, open a PR.
   - `SKIPPED (dirty)` → show `git status --short`; suggest [[np-core-contribute]] or a stash.
   - `DIVERGED` → surface both sides; ask the user how to resolve, don't auto-resolve.

## What this skill does NOT do / why it's safe

Full list — no autostash/rebase, never a direct push to a protected branch,
doesn't re-run one-off setup scripts, and doesn't re-install the OS scheduler
(that's [[np-core-onboard]]'s job) — plus the safety rationale for running
this before every cron-touched session, in `references/scope-and-caveats.md`.
