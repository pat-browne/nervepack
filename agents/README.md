# nervepack: scheduled agents

Weekly agents keep the engine alive: one local cron for memory, plus
default-on local crons for skill refine and compact. Their prompts live next to
this file. This README is the operator's manual for installing, running, and
optionally offloading them to a cloud routine.

## Topology

| When (local) | Agent | Where | Prompt file | Job |
|---|---|---|---|---|
| Sun 08:00 | `memory-promote` | local cron | `memory-promote.md` | Promote durable entries from your local memory store (`~/.claude/projects/<your-project>/memory/`) into the right skill, archive stale entries. **Local-only — cloud agents can't reach the memory store.** |
| Sun 09:30 | `nervepack-refine` | local cron (default-on) | `np-flow-scheduled-refine.md` | Lint frontmatter, audit cross-refs, check vendor sha. Toggle off with `maintain.refine=off`. |
| Wed 10:00 | `nervepack-compact` | local cron (default-on) | `np-flow-weekly-compact.md` | Dedup (auto-merge ≥0.85 Jaccard; propose 0.4–0.85). Splits for >300-line skills go to `compact-proposals/`. Toggle off with `maintain.compact=off`. |

Order: `memory-promote` (writes new content) → `nervepack-refine` (lints what
just got written) → two days later, `nervepack-compact` (dedups the
accumulated state).

## Installing on a new machine

### All scheduled jobs (cron: Linux / macOS fallback)

```bash
~/Code/nervepack/engine/setup/70-install-memory-cron.sh
```

Idempotent. Installs `memory-promote`, `episodic-maintain`, `aggregate-metrics`,
`skill-maintain`, `nervepack-refine`, and `nervepack-compact` under their marker
comments. Verify:

```bash
crontab -l | grep nervepack-
```

### All scheduled jobs (launchd: macOS preferred)

```bash
~/Code/nervepack/engine/setup/70-install-memory-launchd.sh
```

Installs the same jobs as LaunchAgents. Verify:

```bash
launchctl list | grep com.nervepack
```

## Running an agent on-demand (debugging)

### memory-promote (local)
```bash
python3 ~/Code/nervepack/engine/nervepack_engine/cli.py cron memory-promote
tail -50 ~/.cache/nervepack/memory-promote.log
```

### nervepack-refine (local cron)
```bash
python3 ~/Code/nervepack/engine/nervepack_engine/cli.py cron refine
tail -50 ~/.cache/nervepack/refine.log
```

### nervepack-compact (local cron)
```bash
~/Code/nervepack/engine/setup/77-run-compact.sh
tail -50 ~/.cache/nervepack/compact.log
```

## Disabling / removing

- **Local cron (memory-promote):** `crontab -l | grep -vF nervepack-memory-promote | crontab -`
- **Local cron (refine):** `np-core-toggle maintain.refine off`, or remove with `crontab -l | grep -vF nervepack-refine | crontab -`
- **Local cron (compact):** `np-core-toggle maintain.compact off`, or remove with `crontab -l | grep -vF nervepack-compact | crontab -`

## Authentication notes

- Local cron jobs run `np-llm.sh` (→ `claude -p` on the claude backend), which
  uses the OAuth token in `~/.claude/.credentials.json`. Tokens auto-refresh
  while in use; if the box sits idle for weeks and the token lapses, the cron
  will fail silently. Check `~/.cache/nervepack/refine.log` /
  `~/.cache/nervepack/compact.log` after the first run to confirm authentication
  worked. Re-running `claude` interactively refreshes the token.
- On a non-Claude host, set `NP_LLM_BACKEND=local` + `NP_LLM_AGENT_CMD` before
  these crons run (see `engine/setup/np-llm.sh` for the backend contract).

## Optional offload: cloud routines or OSS runners

`nervepack-refine` and `nervepack-compact` run as local crons by default. If
you prefer to offload them to a cloud routine (e.g. a claude.ai scheduled
routine) or an OSS runner (e.g. GitHub Actions), the agent prompts in
`np-flow-scheduled-refine.md` and `np-flow-weekly-compact.md` are already
written to work in either context. They reference "this repo at your working
directory" and carry no account or provider hardcode.

To set up a cloud routine:

1. In an active Claude Code session, invoke the `schedule` skill or its
   slash form: `/schedule`
2. Paste the contents of the prompt file (everything under `## Prompt`) as
   the routine body.
3. Set the cron expression:
   - `nervepack-refine`: `0 15 * * 0` (Sun 15:00 UTC)
   - `nervepack-compact`: `0 15 * * 3` (Wed 15:00 UTC)
4. Disable the matching local cron so they don't race:
   `crontab -l | grep -vF nervepack-refine | grep -vF nervepack-compact | crontab -`

A full provider-agnostic scheduler seam (`NP_SCHED_BACKEND`) is tracked as
[issue #16](https://github.com/pat-browne/nervepack/issues/16). That's Phase 2.
