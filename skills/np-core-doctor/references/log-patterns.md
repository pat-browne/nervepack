# Log patterns — why a session wasn't captured

The doctor reports whether the machinery is *wired*. These logs say what it
*did*. Read them when a session is missing from the episodic layer or the
dashboard, or when a cron looks like it ran but produced nothing.

Every string below is emitted by
`engine/nervepack_engine/hooks/backcapture_sweep.py` or
`engine/nervepack_engine/hooks/session_flush.py` — grep the hook if you need the
surrounding condition.

## `~/.cache/nervepack/backcapture.log` — the reliable capture path

The SessionStart sweep is what actually captures prior sessions; SessionEnd is
best-effort and `/exit` skips it entirely (ARCHITECTURE invariant 12). So this
log, not the SessionEnd one, is where a missing session is explained.

| Pattern | Meaning | Action |
|---|---|---|
| `sweep skipped: another sweep already running` | Lock contention from concurrent session starts | None — normal; the next sweep drains the backlog |
| `aborting sweep: backend auth failed (…)` | Auth broken; every queued session skipped | Fix auth ([[np-env-claude-scheduled-auth-token]]), retries resume on their own |
| `back-captured <sid> (project <name>)` | Captured and evaluated | — |
| `sweep done: N captured, M still queued` | Normal completion | `M > 0` just means more work waits for the next sweep |
| `retry-queued <sid> (transient capture failure)` | Model returned unusable output; retries up to 5× | Usually self-heals; repeated entries for one sid are the signal |
| `gave up on <sid> after N attempts` | Retry limit hit — permanently dropped | No recovery path; the transcript is still on disk if you want it by hand |
| `dropped <sid> (transcript missing …)` | Transcript gone before processing | Lost; normal for ephemeral/test sessions |

A session that never appears in this log at all was never *enqueued* — check
the `memory.backcapture` toggle and `backcapture_days` (the discovery window).

## `~/.cache/nervepack/session-flush.log` — inbox → committed layer

| Pattern | Meaning |
|---|---|
| `skip: within Ns flush interval (age Xs)` | Throttled (default 900 s); the daily crons backstop anything missed |
| `skip: another flush is already running` | Lock contention — serializes concurrent session-ends |
| `flush start` … `flush done` | Normal cycle |

A throttled flush is not a lost flush: the inbox persists and the daily
`memory-promote` / `episodic-maintain` / `aggregate-metrics` crons drain it.

## `~/.cache/nervepack/drift-guard.log` — the spec-drift gate

One line per adjudication, shaped
`<ts> drift-guard <VERDICT> sid=<session> <detail>`.

| Pattern | Meaning | What to do |
|---|---|---|
| `PASS <path> in radius of <spec>` | The edit was inside the declared `blast_radius` | Nothing; this is the normal case on an adopted repo |
| `DENY <path> outside radius of <spec>` | The edit was blocked | Widen the spec's `blast_radius` with a `## Deviations` entry, or supersede the spec. Never widen silently |
| `WARN <path> outside radius of <spec> (enforce off)` | Same violation, downgraded | `gates.drift_guard.enforce` is off. Turn it back on, or accept that drift is being recorded rather than prevented |
| `WARN <spec> declares no blast_radius` | The spec exists but grants nothing | Fill in `blast_radius:`. `spec-guard` fails the branch in CI until you do |

**An empty log is the expected state on most machines.** The hook stays silent
wherever it has no jurisdiction — outside a git repo, on a detached HEAD, or in
any repo with no `change-specs/<branch-slug>.md`. That silence is deliberate:
logging every allowed Write and Edit machine-wide would bury the four lines
above. So a missing log means "nothing to adjudicate", never "the hook is
broken".

To confirm the hook is wired at all, check that `settings.json` carries both
rows — `grep -c 'hook drift-guard' ~/.claude/settings.json` returns 2 — rather
than reading anything into an empty log.
