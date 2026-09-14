---
name: np-core-doctor
description: Run and interpret nervepack's health check (cli.py doctor) — when to use it, what each check means, how to fix FAIL/WARN results. Use post-install, after moving the repo, when a nervepack feature stops working, or when the user says "run the doctor" / "check nervepack health" / "/np-doctor".
---

# np-core-doctor — health check runbook

## Run it

```bash
python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py" doctor
```

Or from the MCP tool: call `nervepack_doctor` (output identical to the CLI). The doctor
runs entirely in-process (Python, `engine/nervepack_engine/np_doctor.py`) — no bash required.

## Output format

```
  [MUST  ] llm-cli                PASS
  [SHOULD] dashboard-data         WARN (run cli.py setup link-dashboard-data)
```

- **MUST** — feature is broken without this; doctor exits non-zero if any MUST fails.
- **SHOULD** — advisory shortfall; doctor still exits 0.
- Status: `PASS` / `FAIL (reason)` / `WARN (reason)` / `MISSING` / `UNSUPPORTED`.

## Checks and fixes

### MUST tier

| Check | What it verifies | Fix |
|---|---|---|
| `knowledge` | Skill symlinks exist (`~/.claude/skills/np-core-sync/SKILL.md`) | Re-run `cli.py setup link-skills` |
| `llm-cli` | the model seam (`np_model.py complete`) returns output | Auth: set `ANTHROPIC_API_KEY` or run `claude /login`; path: check `CLAUDE_BIN` |
| `git-sync` | Repo has a remote | `git remote add origin <url>` |
| `toggles` | `np_toggle.py enabled` resolves | Check `python3 engine/nervepack_engine/np_toggle.py enabled <feature>` runs in the failing hook/script |
| `content` | `NP_CONTENT_DIR` resolves to a real dir | Set `NP_CONTENT_DIR` or write `~/.config/nervepack/content-dir`; single-repo users: write the path to the engine root |

### SHOULD tier

| Check | Fix |
|---|---|
| `team` | Set `NP_TEAM_DIR` or `~/.config/nervepack/team-dir` if you have a team overlay; otherwise safe to ignore |
| `dashboard-data` | `python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py" setup link-dashboard-data` |
| `hook-scripts` | Re-run the failing bootstrap (the error names the missing script) |
| `session-start` | Re-run `cli.py setup install-hooks` (registers every lifecycle hook from `engine/setup/hooks.manifest`) |
| `session-end-capture` | Re-run `cli.py setup install-hooks` |
| `session-end-flush` | Re-run `cli.py setup install-hooks` |
| `scheduled-maint` | Re-run `cli.py setup install-memory-cron` (Linux), `install-memory-launchd` (macOS), or `install-memory-schtasks` (Windows) |
| `scheduled-auth-token` | Missing or in its rotation window: `bash engine/setup/62-install-scheduled-auth-token.sh` (`--rotate` to force). Fixes "Not logged in" failures in memory-promote/refine/compact logs — those crons run under launchd/cron, which don't inherit the interactive session's OAuth. |
| `pii_filter_full` | `python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py" setup install-pii-deps` |

## Common failure patterns

**`llm-cli` FAIL on Windows** — `--bare` was historically passed and skips keychain reads;
fixed in engine ≥ commit 6e98a88. Also check that `ANTHROPIC_API_KEY` is set if using
API-key auth.

**`content` PASS with implicit-fallback warning** — writers (episodic-maintain, metrics)
skip commits until `NP_CONTENT_DIR` is explicit. Set it to avoid silent no-ops.

**`dashboard-data` WARN after moving the repo** — the symlink points to the old path;
re-run `cli.py setup link-dashboard-data`.

**Adapter checks report MISSING** — no `~/.config/nervepack/adapter.json` yet; run the
onboarding flow ([[np-core-onboard]]) to wire the adapter and generate the file.

**Doctor passes but a session wasn't captured.** The doctor checks wiring, not
outcomes. Read `~/.cache/nervepack/backcapture.log` (the reliable capture path) and
`session-flush.log`. Every bail/success string is decoded in
references/log-patterns.md.

**Doctor all-green but real metrics or episodic records stop appearing for
weeks, with no error anywhere.** Doctor has no check for `memory.backcapture`.
It verifies hooks are registered. It never checks that the toggles those hooks
early-return on are actually on.

`backcapture-sweep` (SessionStart) is not a redundant backstop. Claude Code
kills slow SessionEnd `claude -p` hooks before they finish. `/exit` skips
SessionEnd entirely.

So it bails on most real sessions with an empty-transcript or missing-path
error. `np-evaluator.log`, on the version this was written against, reads
`empty transcript extraction for <no path>` (exact string may drift).

With backcapture off, that bail has no catch. `evaluator(metrics)` cron
commits keep reporting "0 record(s)" correctly, since the inbox really is
empty. The bug is upstream, not in the aggregator.

Check by hand, from the repo root:
`python3 engine/nervepack_engine/np_toggle.py enabled memory.backcapture`
(expected `on` or `off`; `FileNotFoundError` means wrong `NP_DIR`). Also read
`~/.config/nervepack/toggles.local` directly, since a local override there is
invisible in the committed `toggles.conf` defaults.

As of this writing, the hook returns before touching its lock file or log.
So `backcapture-sweep.lock` and `backcapture.log` both freeze at the moment
the toggle went off (verify this still holds if the early-return path
changes).

Fix: remove or flip `memory.backcapture=off` in `toggles.local`, then
re-check with the same command above. Only new sessions pick this up. A
running session won't see it until its next `SessionStart`.

Two distinct causes look identical from "the dashboard shows old data".
(1) `metrics.js` needs a rebuild (opening the dashboard triggers
`dashboard/build.py`, which regenerates it from `metrics.jsonl`).
(2) `metrics.jsonl` has no new records, because the inbox is empty (this
pattern). Rebuilding does nothing for cause (2).

Tell them apart with `tail -1 metrics.jsonl | jq .ts`. Hours or days old
means cause (2).

**Doctor is all green but the dashboard shows stale or missing suggestions, or the
content repo's commit count has diverged from origin/main.** Not yet a doctor
check, tracked as [nervepack#329](https://github.com/pat-browne/nervepack/issues/329)
(roadmap label). Until that lands, green does not rule this out.

The `content` check only verifies `NP_CONTENT_DIR` resolves to a real dir. It
never checks that dir is on `main`.

A prior session can leave the content repo on a feature or capture branch.
Every later cron (episodic-maintain, evaluator) then commits to that stale
branch instead.

A second checkout still on `main` runs its own parallel cron stream at the
same time. That's a silent split-brain that can run for days unnoticed.

Check by hand (resolve the dir first, same as [[np-core-contribute]]):
```
CONTENT="$(python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/np_content.py" content_dir)"
STALE_BRANCH="$(git -C "$CONTENT" branch --show-current)"   # should be main
git -C "$CONTENT" fetch origin   # fails if offline or auth is stale; fix that before trusting the two log lines below
git -C "$CONTENT" log --oneline main..HEAD
git -C "$CONTENT" log --oneline HEAD..origin/main
```

If either log shows commits, see references/split-brain-fix.md for the full
merge, rebuild, and verify procedure.

## After fixing

Re-run the doctor; exit 0 + "MUST tier OK ✓" means the engine is healthy.
