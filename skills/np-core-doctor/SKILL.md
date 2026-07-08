---
name: np-core-doctor
description: Run and interpret nervepack's health check (np-doctor.sh) — when to use it, what each check means, how to fix FAIL/WARN results. Use post-install, after moving the repo, when a nervepack feature stops working, or when the user says "run the doctor" / "check nervepack health" / "/np-doctor".
---

# np-core-doctor — health check runbook

## Run it

```bash
bash ~/Code/nervepack/engine/setup/np-doctor.sh
```

Or from the MCP tool: call `nervepack_doctor` (output identical to the CLI).

## Output format

```
  [MUST  ] llm-cli                PASS
  [SHOULD] dashboard-data         WARN (run 35-link-dashboard-data.sh)
```

- **MUST** — feature is broken without this; doctor exits non-zero if any MUST fails.
- **SHOULD** — advisory shortfall; doctor still exits 0.
- Status: `PASS` / `FAIL (reason)` / `WARN (reason)` / `MISSING` / `UNSUPPORTED`.

## Checks and fixes

### MUST tier

| Check | What it verifies | Fix |
|---|---|---|
| `knowledge` | Skill symlinks exist (`~/.claude/skills/np-core-sync/SKILL.md`) | Re-run `30-link-skills.sh` |
| `llm-cli` | `np-llm.sh complete` exits 0 with output | Auth: set `ANTHROPIC_API_KEY` or run `claude /login`; path: check `CLAUDE_BIN` |
| `git-sync` | Repo has a remote | `git remote add origin <url>` |
| `toggles` | `np_enabled` function is available | Source `np-toggle-lib.sh` in the failing hook/script |
| `content` | `NP_CONTENT_DIR` resolves to a real dir | Set `NP_CONTENT_DIR` or write `~/.config/nervepack/content-dir`; single-repo users: write the path to the engine root |

### SHOULD tier

| Check | Fix |
|---|---|
| `team` | Set `NP_TEAM_DIR` or `~/.config/nervepack/team-dir` if you have a team overlay; otherwise safe to ignore |
| `dashboard-data` | `bash ~/Code/nervepack/engine/setup/35-link-dashboard-data.sh` |
| `hook-scripts` | Re-run the failing bootstrap (the error names the missing script) |
| `session-start` | Re-run `51-install-nervepack-directive-hook.sh` (+ `52/53/56` for other hooks) |
| `session-end-capture` | Re-run `52-install-episodic-hooks.sh` |
| `session-end-flush` | Re-run `54-install-session-flush-hook.sh` |
| `scheduled-maint` | Re-run `70-install-memory-cron.sh` (Linux/macOS) or `70-install-memory-schtasks.sh` (Windows) |
| `pii_filter_full` | `bash ~/Code/nervepack/engine/setup/25-install-pii-deps.sh` |

## Common failure patterns

**`llm-cli` FAIL on Windows** — `--bare` was historically passed and skips keychain reads;
fixed in engine ≥ commit 6e98a88. Also check that `ANTHROPIC_API_KEY` is set if using
API-key auth.

**`content` PASS with implicit-fallback warning** — writers (episodic-maintain, metrics)
skip commits until `NP_CONTENT_DIR` is explicit. Set it to avoid silent no-ops.

**`dashboard-data` WARN after moving the repo** — the symlink points to the old path;
re-run `35-link-dashboard-data.sh`.

**Adapter checks report MISSING** — no `~/.config/nervepack/adapter.json` yet; run the
onboarding flow ([[np-core-onboard]]) to wire the adapter and generate the file.

## After fixing

Re-run the doctor; exit 0 + "MUST tier OK ✓" means the engine is healthy.
