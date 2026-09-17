---
name: np-flow-quota-watch
description: Detect a claude.ai usage-limit (quota) violation and get nudged to resume automatically once it resets. Use when a session hit "usage limit reached", when debugging why the resume nudge didn't fire, or when asked to check quota-watch status, install/enable/disable it, or adjust its resume delay.
---

# np-flow-quota-watch

Watches for the `Claude AI usage limit reached|<unix_ts>` message and gets
you nudged to type "continue" one minute after the limit resets.

## How it triggers

Two paths feed the same detector in `engine/nervepack_engine/np_quota_watch.py`:

- **`quota-detect` Stop hook** — fires after every turn, reads that turn's
  transcript, and schedules a nudge the moment the message appears.
- **`quota-watch` cron** — runs every 30 minutes, scans transcripts touched
  in the last 35 minutes, and catches a limit hit mid-tool-call where no
  Stop event fired at all. It also fires an overdue nudge if the precise
  `at` job never ran.

## Resume mechanism

A desktop notification (`notify-send` on Linux, `osascript` on macOS) one
minute after the API's own reset timestamp, telling you to type "continue".
No tmux injection, no headless `claude -p` respawn — the interactive
session gets nudged, not driven.

Precise timing needs the `at` package (`sudo apt install -y at`, already
in `np_bootstrap._APT_PACKAGES`). Without `at`, the nudge still fires, but
only on the next 30-minute cron pass after reset.

## Debugging

```bash
cat ~/.cache/nervepack/quota-watch-state.json   # last detected/scheduled/notified
tail -30 ~/.cache/nervepack/quota-watch.log
python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py" cron quota-watch
```

`at -l` lists any pending scheduled nudge jobs. `crontab -l | grep quota-watch`
confirms the 30-min cron is installed.

## Toggle

`np-core-toggle quota_watch on|off`, or set the resume delay:
`cli.py toggle param quota_watch.resume_delay_s 60`.

## Installing on a new machine

Part of the standard install: `cli.py setup install-hooks` registers the
Stop hook, `cli.py setup install-memory-cron` installs the 30-min cron.
Both already run as part of nervepack onboarding — see `np-core-onboard`.
