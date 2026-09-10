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

**Doctor is all green but the dashboard shows stale or missing suggestions, or the
content repo's commit count has diverged from origin/main.** The `content` check
only verifies `NP_CONTENT_DIR` resolves to a real dir. It never checks that dir is
on `main`. A prior session can leave the content repo on a feature or capture
branch.

Every later cron (episodic-maintain, evaluator) then keeps committing to that
stale branch instead of `main`. A second checkout still on `main` runs its own
parallel cron stream at the same time. That is a silent split-brain that can run
for days before anyone notices.

Check by hand (resolve the dir first, same as [[np-core-contribute]]):
```
CONTENT="$(python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/np_content.py" content_dir)"
STALE_BRANCH="$(git -C "$CONTENT" branch --show-current)"   # should be main
git -C "$CONTENT" fetch origin
git -C "$CONTENT" log --oneline main..HEAD
git -C "$CONTENT" log --oneline HEAD..origin/main
```

Fix, from the stale branch. Stop the episodic-maintain/evaluator cron on this
machine first, so it can't commit mid-merge:
```
git -C "$CONTENT" merge main
```
If that conflicts, the conflicts land in generated files: `metrics.jsonl`,
`dashboard/data/metrics.js`, `INDEX.md`. Don't pick a side.

Rebuild each from the merged source, per [[np-kb-git-gotchas]] (generated-file
conflicts). A picked side silently drops the other branch's real session data.

`metrics.jsonl` is one JSON object per line, keyed by `session_id` and `ts`.

"Union and re-prune" means this: take every line from both `git show :2:`
(ours) and `:3:` (theirs). Keep one copy of each exact duplicate line, sorted
by `ts`.

Then drop any record older than `evaluator.retain_days` (default 90 days)
from now. That's the same rule `np_aggregate.py`'s `_prune_metrics()` already
applies on every normal run.

`metrics.js` and `INDEX.md` are pure derived output, so just regenerate:
```
python3 "${NP_DIR:-$HOME/Code/nervepack}/dashboard/build.py" "$CONTENT/dashboard/data/metrics.jsonl" "$CONTENT/dashboard/data/metrics.js"
python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/setup/np_generate_index.py"
```
Then commit and finish the merge:
```
git -C "$CONTENT" add -A
git -C "$CONTENT" commit -m "merge: reconcile main and the stale branch"
git -C "$CONTENT" checkout main
git -C "$CONTENT" merge --ff-only "$STALE_BRANCH"
```
`merge --ff-only` errors instead of doing anything silent if the branches
still diverge here. That means the step above wasn't finished on both sides.

Re-run `git -C "$CONTENT" merge main` from the stale branch first.
```
git -C "$CONTENT" push origin main
git -C "$CONTENT" branch -D "$STALE_BRANCH"
```

Not yet a doctor check. Tracked as
[nervepack#329](https://github.com/pat-browne/nervepack/issues/329) (roadmap
label): assert `NP_CONTENT_DIR`'s checked-out branch is `main`.

## After fixing

Re-run the doctor; exit 0 + "MUST tier OK ✓" means the engine is healthy.
