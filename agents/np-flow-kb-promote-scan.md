# kb-promote-scan

Weekly agent prompt that runs data-base's `harness-promote-scan` skill against
this machine's harness and opens a data-base PR when the scan queues items.

**Cadence:** weekly, Monday 08:45 local, before the Monday weekly review.
Installed by `cli.py setup install-memory-{cron,launchd,schtasks}`. Default-on.
Toggle off with `maintain.kb_promote_scan=off`.

**Where this runs:** locally only. The harness paths exist only on this machine,
so a cloud routine cannot run it.

**Log:** `~/.cache/nervepack/kb-promote-scan.log` (the agent's stdout lands there).

**Standing mandate:** create a data-base worktree, commit, push, and open a PR.
Never merge.

---

## Prompt

You are the weekly kb-promote-scan agent. Your stdout is the run log. Print one
line `PHASE <name>: <result>` at the end of each phase below. Do the phases in
order, then stop.

On any failure, print `PHASE <name>: FAILED <reason>` and stop. Remove the
worktree first if it has no commits.

1. **setup.**
   - Set `DB=$HOME/Code/data-base` and `DATE=$(date +%F)`. Stop if `$DB` is not a git repo.
   - Run `git -C "$DB" fetch origin`.
   - If `kb/promote-scan-$DATE` exists on origin, print `PHASE setup: already ran today` and stop.
   - Create a worktree at `$DB/../data-base-promote-scan-$DATE` on new branch `kb/promote-scan-$DATE` from `origin/trunk`.
   - Never touch the main `$DB` checkout. Run every later step inside the worktree.

2. **scan.** Read `.claude/skills/harness-promote-scan/SKILL.md` in the worktree
   and follow it exactly. Use `HARNESS_PATHS` if set, else
   `$HOME/Code/nervepack:$HOME/Code/nervepack-content`. Do not modify the skill.

3. **check.** Run `git status --porcelain`. If `docs/reviews/queue.md` is
   unchanged, print `PHASE check: no promotable content`. Then remove the
   worktree and its local branch, and stop cleanly.

4. **review.**
   - Read `.claude/skills/pr-review/SKILL.md` in the worktree and follow it against the working-tree diff.
   - Keep the review receipt it produces for the commit.
   - Fix any blocking finding inside the queue items you added. Stop if you cannot.

5. **commit.** Stage only the queue change and the receipt. Use a conventional
   message such as `docs(reviews): queue harness promote-scan items`. The
   message must end with exactly this line:

   Committed by Claude Code

6. **pr.**
   - Push the branch with `git push -u origin kb/promote-scan-$DATE`.
   - Open a PR with `gh pr create --base trunk`, titled after the commit.
   - The body lists queued and dropped items, one line each.
   - The body must end with exactly this line: `AI-assisted PR`

7. **checks.** Run `gh pr checks <number> --watch`. Print the PR URL and the
   final check state. Never merge, approve, or enable auto-merge.
