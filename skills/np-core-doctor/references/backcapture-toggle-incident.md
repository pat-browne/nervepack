# Root cause: memory.backcapture off silently stops capture

Deeper trace behind the `backcapture-enabled` doctor check, kept here instead
of in SKILL.md so the runbook stays short.

## Why backcapture-sweep exists at all

`backcapture-sweep` is a SessionStart hook, not a redundant backstop. Claude
Code kills slow SessionEnd `claude -p` hooks before they finish. `/exit`
skips SessionEnd entirely. So the SessionEnd evaluator bails on most real
sessions with an empty-transcript or missing-path error.

`np-evaluator.log` reads `empty transcript extraction for <no path>` when
this happens. The exact bail string lives in
`engine/nervepack_engine/hooks/evaluator.py` and may drift, so grep that file
rather than trusting this quote.

With `memory.backcapture` off, that bail has no catch. `evaluator(metrics)`
cron commits keep reporting "0 record(s)" correctly, since the inbox really
is empty. The bug is upstream in the evaluator/toggle path, not in the
aggregator (`np_aggregate.py`).

## What the toggle being off looks like on disk

`backcapture_sweep.py`'s `run()` checks the toggle before acquiring its lock
or writing any log line. When the toggle is off, `backcapture-sweep.lock` and
`backcapture.log` both freeze at the exact moment the toggle went off, with
no further activity and no error.

This can look like a hung process. It is the early return. `_pid_alive()` on
the frozen lock's PID correctly shows it is dead.

## Verifying by hand

```
python3 engine/nervepack_engine/np_toggle.py enabled memory.backcapture
```

Expected `on` or `off`. `FileNotFoundError` means the wrong `NP_DIR`. Also
read `~/.config/nervepack/toggles.local` directly. A local override there is
invisible in the committed `toggles.conf` defaults, which is exactly what
caused this incident.

## Fix

```
python3 engine/nervepack_engine/cli.py toggle memory.backcapture on
```

Only new sessions pick this up. A session already running waits for its next
`SessionStart`.
