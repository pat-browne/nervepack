# np-core-sync — what this skill does NOT do, and why it's safe

## What this skill does NOT do

- Does not silently rebase, autostash, or merge-with-strategy. The whole
  point is predictability.
- **Never pushes directly to a protected branch.** `local is N ahead` opens a
  PR (see references/outcomes.md) instead of pushing straight to `origin/main`, for the engine
  and for every content layer alike. Pushing *new* content still happens via
  [[np-core-contribute]] or explicit user ask — unchanged.
- Does not re-run non-hook `engine/setup/*.sh` scripts or `cli.py setup <step>`
  bootstrap steps. If a one-off setup step changed (e.g. `install-apt-baseline`
  added a new package), surface that to the user — only `cli.py setup link-skills`
  and the hook installers (`cli.py setup install-hooks`) auto-run on a fast-forward
  (see references/outcomes.md; #106).
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
