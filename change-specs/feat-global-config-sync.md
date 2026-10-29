---
id: 0101
status: accepted
date: 2026-10-26
tier: high
blast_radius:
  - engine/setup/np_global_config.py
  - engine/setup/np_instruction_block.py
  - engine/setup/np_generate_index.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/nervepack_engine/np_toggle.py
  - engine/nervepack_engine/np_sync.py
  - engine/nervepack_engine/np_doctor.py
  - engine/nervepack_engine/cli.py
  - engine/setup/np-mcp-server.py
  - engine/onboard/capabilities.json
  - engine/setup/tests/**
  - docs/ARCHITECTURE.md
  - docs/CONTENT-OVERLAY.md
  - change-specs/feat-global-config-sync.md
---

# 0101: Global host config sync, toggle commit routing, index help flag

## Context and problem statement

Global rules and non-secret host settings drift between machines. Each machine
keeps its own `CLAUDE.md` and `settings.json`.

Two defects sit beside this work. `np_toggle.commit_shared` commits onto whatever
branch the overlay is on. `np_generate_index.py --help` runs the generator and
writes files.

## Considered options

1. Sync the overlay's `config/global-rules.md` and `config/host-settings.json`
   into each host through the managed-block mechanism. Good, because the overlay
   already follows the user across machines. Bad, because it edits host files.
2. Copy whole host files from the overlay. Bad, because it clobbers hooks,
   permissions and env, and risks copying secrets.
3. Do nothing. Bad, because the drift stays invisible.

## Decision

We will add the `global-config` feature (local scope, managed, default on).
Rules go inside a tagged managed block with its own markers. Settings merge only
the base keys plus the file's own `allowlist`, and the overlay wins on those keys.

Marketplaces and plugins load code, so they apply only when trusted.

A marketplace is trusted when the machine already has it with the same source.
It is also trusted when its source or name is a line in the per-machine,
never-synced `~/.config/nervepack/trusted-marketplaces`. A plugin is trusted
when its `@marketplace` is. The doctor lists each skipped item with the line to add.

The sync never touches `hooks`, `permissions` or `env`. It refuses any key named
like a secret, at any depth.

The sync runs at `setup install-hooks` and after a pulling `sync`. It is
idempotent and fail-open. A doctor check reports drift.

Turning the toggle off removes the blocks and the settings keys the sync wrote.
A key goes only while its value is unchanged.

We will route `np_toggle.commit_shared` through `np_git_publish.write_root` and
`publish`. Off main, the flip is re-run in the cron worktree at origin/main.
The diff must change exactly that feature's row, else nothing is committed.

We will make `np_generate_index.py -h` and `--help` print usage and exit 0
without writing.

Chosen option: 1, because it reuses the managed-block mechanism and stays
additive and reversible.

## Non-goals

- No personal content in the engine. The overlay supplies both files.
- No sync of secrets, hooks, permissions or env.
- No team-layer config. Only the personal overlay is read.

## Cross-cutting concerns

- Security: secret-like key names are refused. Untrusted marketplaces and
  plugins are skipped. A toggle commit holds one row only. Rules text is not scanned.
- Privacy: company-neutral wording, no instance data.
- Observability: refusals go to stderr. The doctor reports drift.

## Consequences

- Good, because one overlay edit reaches every machine at the next sync.
- Good, because a toggle flip no longer lands on a feature branch.
- Bad, because a pulled overlay can change a host's global rules without review.
- Neutral, because a settings key removed from the overlay stays on machines.

## Confirmation

`engine/setup/tests/onboard/test_np_global_config.py`,
`engine/setup/tests/toggles/test_commit_shared_route.py` and
`engine/setup/tests/content/test_generate_index_help.py`, run by
`bash engine/setup/tests/run-all.sh`.

## Rollback

Run `cli.py toggle global-config off` on each machine. That removes the rules
blocks and the settings keys the sync wrote. Then revert the PR. The commit
routing and the help flag revert on their own.

## Deviations

- 2026-10-26: added `engine/setup/toggle-schema.json` to the blast radius. A new
  toggle needs a description there, and a test enforces it.
- 2026-10-29: added `engine/setup/np-mcp-server.py` to the blast radius. Its
  dotted-key toggle call now passes the flip to `commit_shared`. The patch
  replay became a row re-run after a Windows failure and a review finding.

