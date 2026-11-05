# kb-promote-scan

Weekday agent prompt that runs data-base's `harness-promote-scan` skill against
this machine's harness. The skill files promotion suggestions as GitHub issues
on `campminder/data-base`, labelled `triage` and `venue:kb`.

**Cadence:** Monday to Friday, 11:00 local.
Installed by `cli.py setup install-memory-{cron,launchd,schtasks}`. Default-on.
Toggle off with `maintain.kb_promote_scan=off`.

**Where this runs:** locally only. The harness paths exist only on this machine,
so a cloud routine cannot run it.

**Log:** `~/.cache/nervepack/kb-promote-scan.log` (the agent's stdout lands there).

**Standing mandate:** read data-base from a throwaway detached worktree of
`origin/trunk`. File issues through the skill. Never commit, push, or open a PR.

**History:** until 2026-11-05 this prompt committed `docs/reviews/queue.md` and
opened a PR. The queue moved to GitHub Issues on 2026-10-19, so those phases
never ran again. The skill already filed issues.

**Prerequisites:** the skill and `docs/systems/review-queue.md` on data-base trunk.
A `gh` login that can file issues on `campminder/data-base`. Phase setup checks both.

**Manual recovery:** a crashed run can leave `data-base-promote-scan-<date>`.
Remove it with `git -C ~/Code/data-base worktree remove --force <path>`.

---

## Prompt

You are the kb-promote-scan agent. Your stdout is the run log. Print one
line `PHASE <name>: <result>` at the end of each phase below. Do the phases in
order, then stop.

On any failure, print `PHASE <name>: FAILED <reason>`. Then run phase cleanup and stop.

1. **setup.**
   - Set `DB=$HOME/Code/data-base` and `DATE=$(date +%F)`. If `$DB` is not a git repo, print `PHASE setup: FAILED $DB is not a git repo` and stop.
   - Run `gh auth status`. If it fails, print `PHASE setup: FAILED gh not authenticated` and stop.
   - Run `git -C "$DB" fetch origin` and `git -C "$DB" worktree prune`.
   - Remove every `$DB/../data-base-promote-scan-*` worktree with `git -C "$DB" worktree remove --force <path>`. They hold no work, since this job never commits. Print `PHASE setup: removed <path>` for each.
   - Create a detached worktree with `git -C "$DB" worktree add --detach "$DB/../data-base-promote-scan-$DATE" origin/trunk`.
   - Confirm `.claude/skills/harness-promote-scan/SKILL.md` and `docs/systems/review-queue.md` exist in the worktree. If either is missing, print `PHASE setup: FAILED missing <paths>`.
   - Never touch the main `$DB` checkout. Run every later step inside the worktree.

2. **scan.**
   - Read `.claude/skills/harness-promote-scan/SKILL.md` in the worktree and follow it exactly. Do not modify it.
   - Use `HARNESS_PATHS` if set, else `$HOME/Code/nervepack:$HOME/Code/nervepack-content`.
   - Do not edit, commit, or push anything in the worktree.
   - Print `PHASE scan: filed <N> issues <urls>`, or `PHASE scan: nothing to file`. If `gh issue create` fails, print `PHASE scan: FAILED <error>`.

3. **report.**
   - Print the skill's report under the scan line, one line per item.
   - List each filed issue, each item held back by the cap, each conflict for `/kb-review`, and each drop with its reason.

4. **cleanup.**
   - Run `git -C "$DB" worktree remove --force <worktree path>`.
   - Print `PHASE cleanup: removed <path>` or `PHASE cleanup: FAILED <reason>`.
   - Never commit, push, open a PR, or close an issue.
