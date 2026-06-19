# §7 recursion guard — loop diagram, incident, and regression test

## Loop diagram

```
SessionEnd ─▶ episodic-capture.sh ─▶ claude -p (summarizer)
     ▲                                     │  (this -p run ALSO fires SessionEnd)
     └─────────────────────────────────────┘   ∞  ~1.5 s/cycle
```

## Observed incident

~1800 transcripts created ~1.5 s apart, each nesting one more `BEGIN INERT SESSION LOG`
wrapper (capture summarizing its own prior output). `np-evaluator.sh` had the identical
bug; even the `71/72/75` crons ignite it, because *their* `claude -p` fires
SessionEnd → capture+evaluator → more `claude -p`. Renaming the prompt delimiter does
**not** fix it; only a re-entry guard does.

## Regression test

Offline (stubbed CLI): with `NERVEPACK_AGENT=1` set, the hook exits 0 without invoking
claude and writes nothing — `setup/tests/episodic/test_capture_reentry_guard.sh`.

## Third-party plugin hooks: the `NERVEPACK_AGENT` marker is not enough — use `--bare`

The re-entry marker above only gates **nervepack's own** hooks. **Third-party plugin
hooks** (installed in the host, e.g. a `security-review` plugin's `PostToolUse:Bash`
hook) do **not** check `NERVEPACK_AGENT`, so they still fire inside a headless agent
session. Observed (2026-06-18): the dashboard's suggestion-"Implement" async agent
(`np-implement-suggestion.sh` → `np-llm.sh agent`) made a commit; the security-review
PostToolUse hook fired on that Bash call and spawned a full Opus review; the parent
`claude` agent waited on the child; and because the wrapper captured agent output via
`$(...)`, the pipe stayed open until all writers exited — so `write_status done` never
ran and the dashboard showed "Implementing…" forever.

**Fix:** add the real flag **`--bare`** (NOT `--no-hooks`, which doesn't exist — verify
with `claude --help | grep -i hook`) to headless `claude -p` calls. `--bare` skips
hooks, LSP, plugin sync, and auto-memory — exactly the interactive machinery a detached
background agent must not run. In nervepack it's set in `np-llm.sh` for the `claude`
backend's `agent` *and* `complete` modes (the `local` backend has no Claude hooks).
Defense-in-depth: wrap the agent call in `timeout` and fail-open (write a failed status +
release the lock) so a hung agent can't wedge the job. Tests: `tests/llm/test_np_llm.sh`
(asserts `--bare` present in claude calls, absent in local) + `tests/evaluator/test_implement.sh`
(timeout → status=failed, lock released).
