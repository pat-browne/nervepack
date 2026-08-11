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
