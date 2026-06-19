# nervepack — scheduled agents

Three weekly agents keep `nervepack` alive: one local cron job, two cloud
remote routines. Their prompts live next to this file. This README is the
operator's manual for installing, listing, updating, and running them.

## Topology

| When (local) | Agent | Where | Prompt file | Job |
|---|---|---|---|---|
| Sun 08:00 | `memory-promote` | local cron | `memory-promote.md` | Promote durable entries from your local memory store (`~/.claude/projects/<your-project>/memory/`) into the right skill, archive stale entries. **Local-only — cloud agents can't reach the memory store.** |
| Sun 09:00 | `nervepack-refine` | cloud routine | `scheduled-refine.md` | Lint frontmatter, audit cross-refs, check vendor sha. |
| Wed 09:00 | `nervepack-compact` | cloud routine | `weekly-compact.md` | Dedup (auto-merge ≥0.85 Jaccard; propose 0.4–0.85). Splits for >300-line skills go to `compact-proposals/`. |

Order: `memory-promote` (writes new content) → `nervepack-refine` (lints what
just got written) → two days later, `nervepack-compact` (dedups the
accumulated state).

## Cloud routine trigger IDs

The cloud routines are owned by your own AI account, so their trigger IDs are
per-account. Record yours here when you create them so they're not lost:

| Agent | Trigger ID |
|---|---|
| `nervepack-refine` | `<your-trigger-id>` |
| `nervepack-compact` | `<your-trigger-id>` |

If an ID goes stale (deleted, recreated), update this file and the references in the
agent prompt headers.

## Installing on a new machine

### Local cron (memory-promote)

```bash
~/Code/nervepack/setup/70-install-memory-cron.sh
```

Idempotent. Adds the entry under the marker `# nervepack-memory-promote` to
the user crontab. Verify:

```bash
crontab -l | grep nervepack-memory-promote
```

### Cloud routines (nervepack-refine, nervepack-compact)

In an active Claude Code session, invoke the `schedule` skill or its
slash form:

```
/schedule
```

Paste the contents of `agents/np-flow-scheduled-refine.md` (everything under
`## Prompt`) for `nervepack-refine`, then repeat for `nervepack-compact` using
`weekly-compact.md`. Cron expressions:

- `nervepack-refine`: `0 15 * * 0` (Sun 15:00 UTC)
- `nervepack-compact`: `0 15 * * 3` (Wed 15:00 UTC)

Settings used for both:
- Model: `claude-sonnet-4-6`
- Environment: your account's default environment
- Source: your clone of this repo
- Allowed tools: `Bash, Read, Write, Edit, Glob, Grep`

Record the new trigger IDs in the table above when you create them.

## Running an agent on-demand (debugging)

### memory-promote (local)
```bash
~/Code/nervepack/setup/71-run-memory-promote.sh
tail -50 ~/.cache/nervepack/memory-promote.log
```

### nervepack-refine / nervepack-compact (cloud)
Via the `schedule` skill: `RemoteTrigger run` with the trigger ID. Or
from your AI host's routine UI: open the routine page and click "Run now".

## Disabling / removing

- **Local cron:** `crontab -l | grep -vF nervepack-memory-promote | crontab -`
- **Cloud routines:** the API can't delete them — remove them via your host's
  routine UI. To temporarily disable, `RemoteTrigger update {trigger_id, body: {enabled: false}}`.

## Authentication notes

- `memory-promote` runs `claude -p` from cron, which uses the OAuth token
  in `~/.claude/.credentials.json`. Tokens auto-refresh while in use; if
  the box sits idle for weeks and the token lapses, the cron will fail
  silently. Check `~/.cache/nervepack/memory-promote.log` after the first run
  to confirm authentication worked. Re-running `claude` interactively
  refreshes the token.
- Cloud routines run as the account that owns them. Pushes to the engine repo
  happen via the cloud environment's git auth, not local creds.
