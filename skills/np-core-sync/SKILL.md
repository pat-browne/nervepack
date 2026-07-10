---
name: np-core-sync
description: Sync ~/Code/nervepack with origin/main using strict-safe semantics (fast-forward only; never auto-rebase or autostash). Use when the user says "sync nervepack", "pull nervepack", "what's new in nervepack", when starting work after a known cron run, or when the SessionStart status file reports anything other than "up to date".
---

# np-core-sync

## Behavior contract

The underlying script (`~/Code/nervepack/engine/setup/40-sync-nervepack.sh`) is intentionally
*defensive*: it never modifies a dirty working tree, never autostashes, and
never rebases. Every run produces one of five outcomes, written to
`~/.cache/np-core-sync-status`:

| Outcome | Meaning | What this skill does |
|---|---|---|
| `up to date` | local == origin/main | report and stop |
| `fast-forwarded N commit(s)` | safe pull happened | report what changed |
| `local is N ahead of origin/main` | unpushed local commits | push (auto-approved) |
| `SKIPPED (dirty)` | uncommitted edits block sync | surface diff, suggest commit/stash |
| `DIVERGED` | local and remote both have unique commits | surface both sides, ask user how to resolve |

The `SessionStart` hook calls the script silently in the background, so its
output only lives in the status file. This skill's job is to surface that
state and act on it.

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
   ~/Code/nervepack/engine/setup/40-sync-nervepack.sh --verbose
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
Show the unpushed commits with `git -C ~/Code/nervepack log @{u}..HEAD --oneline`,
then **push without asking** — Pat set a standing preference (2026-06-03): always
auto-approve nervepack **sync** pushes (already-committed local state), no per-push
confirmation. New content writes still go through [[np-core-contribute]]'s push
gate. Push the current branch to its tracking remote;
if it's a main-tracking branch, fast-forward-push the pinned SHA to `origin/main`
per the concurrency protocol. Never force-push; on non-fast-forward, surface it.

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
- Does not push **except** in the `local is N ahead` outcome (the standing
  auto-approval above). Pushing *new* content happens via [[np-core-contribute]]
  or explicit user ask.
- Does not re-run non-hook `engine/setup/*.sh` scripts. If a one-off setup
  script changed (e.g. `00-apt-baseline.sh` added a new package), surface that
  to the user — only `30-link-skills.sh` and every `5[0-9]-install-*.sh` hook
  installer auto-run on a fast-forward (see above; #106).
- **Does** edit `~/.claude/settings.json` as a side effect of the fast-forward
  case above (since #106) — if a hook installer's registered command changed,
  the live settings.json is updated in the same sync, no separate step needed.
  Before #106 this was a real gap: a merged hook fix could sync clean while
  settings.json ran the stale command for days (symptom: "we fixed this
  yesterday" for any hook-command change, or unexplained SessionStart delays
  from an un-redirected backgrounded hook). If you ever see that symptom again,
  check the live settings.json hook strings against the installer source —
  they can only diverge for setup scripts outside the `5[0-9]-install-*.sh`
  glob (e.g. `61-install-resume-hook.sh`), which still need a manual re-run.

## Why this is safe across many session starts before cron runs

Because nothing in the auto path ever touches a dirty working tree or
rewrites local history. Your in-progress edits are inert to the hook. The
only autopilot action is fast-forward, which is mathematically a no-op for
divergent state. If the cron and you both edit the same files, the second
session start sees `DIVERGED`, refuses to merge, and waits for you to
invoke this skill interactively.
