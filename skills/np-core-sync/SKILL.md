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

**The personal content overlay gets the same ff-only treatment** as team
layers, gated by `sync.content` (default on; no-op on a single-repo legacy
layout). No layer or the engine ever auto-pushes — `np_sync.py` has no push
code path. Layer outcomes are non-fatal stderr notes, not the status file
(engine-only): `"content layer <path> not fast-forwarded (diverged/ahead/no
upstream) — left as-is"` / `"... has local edits — skipping pull"`.

Every sync also validates each layer's `.nervepack/layout.json` (the same
check `cli.py doctor`'s `layer-layout` capability runs) and prints
`"layout manifest invalid in <path>: <error>"` to stderr on a corrupt
manifest. This is non-fatal, like the layer notes above. Surface this line to
the user if you see it: a bad manifest silently misplaces the next
[[np-core-contribute]] write into that layer.

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

2. **Run the sync** (idempotent, writes a fresh status):
   ```bash
   python3 ~/Code/nervepack/engine/nervepack_engine/cli.py sync --verbose
   ```

3. **Branch on the outcome.**

### `up to date`
Report and stop.

### `fast-forwarded N commit(s)`
Show the user `git -C ~/Code/nervepack log <prev>..HEAD --oneline` so they see what
landed. The linker already ran inside the script, and (as of #106) so has every
`5[0-9]-install-*.sh` hook installer — a pulled change to a hook's registered
command (e.g. a stdout/stderr redirect fix) reaches `~/.claude/settings.json` in
the same sync, not on some later manual re-install. No further action.

### `local is N ahead`
**No direct push to main — every push goes through a PR.** (Superseded
2026-08-13: the prior standing preference auto-pushed already-committed local
state straight to `origin/main`. That is gone.) Show the unpushed commits
(`git -C ~/Code/nervepack log @{u}..HEAD --oneline`), then create a branch,
push it, and open a PR:
```bash
git -C ~/Code/nervepack checkout -b sync/<short-sha>-<date>
git -C ~/Code/nervepack push -u origin sync/<short-sha>-<date>
gh pr create --repo <owner>/nervepack --fill
```
Report the PR URL. If already on a feature branch (not `main`) with an
upstream, just push it and open the PR from there — no need to branch again.
If `gh` is missing, unauthenticated, or the push is rejected: degrade to the
old plain report ("N commits ahead — not pushed") and surface the specific
failure; never fall back to a direct push. **This only ever happens here**,
in this skill's own interactive steps — never from the background
`SessionStart` hook, which has no model in the loop to make this call and
keeps today's passive report-only behavior for engine, team, and content
layers alike.

### `SKIPPED (dirty)`
Run `git -C ~/Code/nervepack status --short`. Show the user. Suggest the right next
step based on intent:
- "I'm done with these changes" → invoke [[np-core-contribute]] to commit + push
- "I'm not done" → suggest `git -C ~/Code/nervepack stash`, then re-run sync, then
  `git stash pop`

### `DIVERGED`
Surface both sides:
```bash
git -C ~/Code/nervepack log @{u}..HEAD --oneline       # local-only commits
git -C ~/Code/nervepack log HEAD..@{u} --oneline       # remote-only commits
```
Do NOT auto-resolve. Ask the user how to proceed. Defaults:
- If the divergence is just lint/format from the cron agent on files the
  user also edited → `git -C ~/Code/nervepack pull --rebase --autostash` and walk
  conflicts with the user.
- If the divergence is a real edit collision → consider whether the user
  wants to keep both sides; surface the diffs.

## What this skill does NOT do

- Does not silently rebase, autostash, or merge-with-strategy. The whole
  point is predictability.
- **Never pushes directly to a protected branch.** `local is N ahead` opens a
  PR (see above) instead of pushing straight to `origin/main`, for the engine
  and for every content layer alike. Pushing *new* content still happens via
  [[np-core-contribute]] or explicit user ask — unchanged.
- Does not re-run non-hook `engine/setup/*.sh` scripts or `cli.py setup <step>`
  bootstrap steps. If a one-off setup step changed (e.g. `install-apt-baseline`
  added a new package), surface that to the user — only `cli.py setup link-skills`
  and the hook installers (`cli.py setup install-hooks`) auto-run on a fast-forward
  (see above; #106).
- **Does** edit `~/.claude/settings.json` as a side effect of the fast-forward
  case above (since #106) — if a hook installer's registered command changed,
  the live settings.json is updated in the same sync, no separate step needed.
  Before #106 this was a real gap: a merged hook fix could sync clean while
  settings.json ran the stale command for days (symptom: "we fixed this
  yesterday" for any hook-command change, or unexplained SessionStart delays
  from an un-redirected backgrounded hook). If you ever see that symptom again,
  check the live settings.json hook strings against `engine/setup/hooks.manifest`
  (the sync re-runs `cli.py setup install-hooks`, which registers every row from
  it). Only non-hook setup scripts outside the `[56][0-9]-install-*.sh` glob
  would still need a manual re-run.
- **Does not re-install the OS scheduler** (launchd / schtasks / cron) — that is
  [[np-core-onboard]]'s step 3, or `cli.py setup install-memory-{cron,launchd,schtasks}`.
  The load-bearing gotcha: **sync updates *code* but never rewrites an OS artifact that
  was already installed on disk.** So a pull that fixes the code which *generates* an
  installed artifact — a plist / crontab / schtasks entry, a managed config file — does
  NOT reach the live entry via sync: git pull updates the source, but the stale generated
  artifact persists until it is re-installed. When such a change lands, point *existing*
  machines at `cli.py onboard` (idempotent; it re-runs the scheduler + doctor), not just
  sync. Concrete case: the 2026-07 doubled-`engine/engine`-path fix in the scheduler
  installers left macOS/Windows scheduled-maintenance jobs silently dead until a re-onboard
  regenerated the plists/tasks — a plain sync would have left them broken.

## Why this is safe across many session starts before cron runs

Because nothing in the auto path ever touches a dirty working tree or
rewrites local history. Your in-progress edits are inert to the hook. The
only autopilot action is fast-forward, which is mathematically a no-op for
divergent state. If the cron and you both edit the same files, the second
session start sees `DIVERGED`, refuses to merge, and waits for you to
invoke this skill interactively.
