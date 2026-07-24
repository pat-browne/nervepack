---
name: np-flow-merge-gate
description: Gate a branch merge on concurrent work finishing, then decide clean-vs-issues. Use when another agent/session/cron is operating on the same repo (a worktree-agent, a cloud routine, a teammate) and you want to merge a branch without colliding — wait for the repo to go quiet, then merge if the diff is clean or ask the user how to proceed if there are conflicts or forbidden trailers. Trigger phrases: "wait to merge", "merge when the other branch finishes", "is it safe to merge yet".
---

# Merge gate — wait out concurrency, then merge on a clean diff

`~/Code/nervepack` is a single working tree with one git HEAD. When a second
session (often a `.claude/worktrees/agent-*` worktree), a cron, or a cloud routine
is committing here too, merging blind risks sweeping their files, orphaning their
commits, or merging a half-finished state. This workflow makes the merge **wait for
quiet, then gate on the diff**. It is the operational front-end to the
"[concurrent session]" rules in `AGENTS.md`.

## When to use

- You have a branch ready to merge **and** you know (or suspect) another agent/
  branch/cron is active in the same repo.
- The git log/worktree changed under you mid-task (a ref moved, a commit vanished).
- The user says "wait for the other branch to finish, then merge."

## The waiter

`cli.py merge-wait` (backed by `engine/setup/np_merge_wait.py`) blocks until the repo
is **quiet** (all refs + HEAD + working tree stable across a full poll interval),
then checks merge-readiness. Read-only — it never commits, merges, or pushes.

```bash
python3 engine/nervepack_engine/cli.py merge-wait --repo ~/Code/nervepack --branch <BR> --base origin/main
```

Cadence: starts at `--interval` 60s, adds `--backoff` 30s each cycle, gives up at
`--timeout` 1800s (30 min). `--settle` (default 2) is how many consecutive
identical samples count as quiet. Run it **after** you've finished your own commits
(your own activity counts as churn and would reset the quiet timer).

Run it in the background and let the host re-invoke you on exit — a 30-minute block
shouldn't hold the foreground.

## Exit codes → what you do

| Exit | Meaning | Action |
|---|---|---|
| **0** `RESULT: CLEAN` | Quiet; branch merges cleanly; no policy issues | **Option 1 — proceed.** Refresh understanding (`git fetch`, re-read the diff), then merge. |
| **2** `RESULT: ISSUES` | Quiet, but merge conflicts and/or forbidden AI-attribution trailers (coding-rules §6) | **Option 2 — stop and notify the user.** Summarize the issues and ask whether to (a) gate the merge until the other branch/agent finishes and re-check, or (b) resolve now (rebase out trailers / resolve conflicts). Do **not** merge unprompted. |
| **3** `RESULT: TIMEOUT` | Repo never settled within `--timeout` | **Notify the user.** The other work is still going; ask whether to keep waiting (re-run, longer timeout) or intervene. |

## Rules carried from the concurrency section

- **Never `git add -A`/`commit -am`** in a shared tree; stage **and** commit explicit
  paths (`git commit -m … -- <paths>`).
- **Tag a backup** (`git tag <name> <sha>`) before any reset/rebase, and prefer
  committing detachable work from an isolated `git worktree` off the committed base.
- On a clean (`exit 0`) gate, still **`git fetch` and treat `origin/main` as the
  source of truth** before merging.
- Strip any forbidden trailer **before** the merge, never after it lands on `main`
  (see [[np-kb-testing-ci]] §4 for the `filter-branch` recipe).

Related: `AGENTS.md` § "Commit conventions" (no AI attribution), [[np-kb-testing-ci]]
(the `filter-branch` trailer-scrub recipe), and the `AGENTS.md` concurrency section this operationalizes.
