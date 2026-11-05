# kb-promote-scan

Weekday agent prompt that runs data-base's `harness-promote-scan` skill against
this machine's harness. The skill writes docs and small skill additions, and files
`triage` issues on `campminder/data-base` for new skills or large skill changes.
This job then gates, commits, and pushes the written files to `trunk`.

**Cadence:** Monday to Friday, 11:00 local.
Installed by `cli.py setup install-memory-{cron,launchd,schtasks}`. Default-on.
Toggle off with `maintain.kb_promote_scan=off`.

**Where this runs:** locally only. The harness paths exist only on this machine,
so a cloud routine cannot run it.

**Log:** `~/.cache/nervepack/kb-promote-scan.log` (the agent's stdout lands there).

**Standing mandate:** work in a throwaway detached worktree of `origin/trunk`.
Push additions straight to `trunk`, as data-base's CONTRIBUTING allows. Never open a PR,
force-push, or touch the main data-base checkout.

**Parameters:** the skill reads `HARNESS_PATHS`, `PROMOTE_TERMS_FILE`, `PROMOTE_MIN_TERMS`,
`PROMOTE_MAX_WRITES`, `PROMOTE_MAX_PROPOSALS`, `PROMOTE_SKIP_DIRS` and `PROMOTE_DRY_RUN`
from the environment. Unset means the skill's default.

**Attribution:** the commit lands in data-base, so it ends with `Committed by Claude Code`
per Campminder's managed settings. AGENTS.md's no-attribution rule covers nervepack only.

**History:** before 2026-11-05 this job committed `docs/reviews/queue.md` and opened a PR.
The queue moved to GitHub Issues on 2026-10-19, so those phases stopped running.

**Manual recovery:** a crashed run can leave `data-base-promote-scan-<date>`.
If it holds an unpushed commit, push it with `git -C <path> push origin HEAD:trunk`.
Otherwise remove it with `git -C ~/Code/data-base worktree remove --force <path>`.

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
   - For each `$DB/../data-base-promote-scan-*` worktree, check `git -C <path> log origin/trunk..HEAD`. Remove it if that is empty. Otherwise keep it and print `PHASE setup: kept <path> (unpushed commit)`.
   - Create `WT=$DB/../data-base-promote-scan-$DATE` with `git -C "$DB" worktree add --detach "$WT" origin/trunk`. If it already exists, print `PHASE setup: FAILED worktree exists, see Manual recovery`.
   - Confirm `.claude/skills/harness-promote-scan/SKILL.md` exists in `$WT`. Run `uv sync --all-extras --dev` there.
   - Never touch the main `$DB` checkout. Run every later step inside `$WT`.
   - Print `PHASE setup: ok <WT path>`.

2. **scan.**
   - Read `.claude/skills/harness-promote-scan/SKILL.md` in `$WT` and follow it exactly. Do not modify it.
   - Print `PHASE scan: wrote <N> files, filed <M> issues <urls>`.
   - If `PROMOTE_DRY_RUN=1`, print the skill's plan, skip to phase report, and commit nothing.
   - If `git status --porcelain` is empty, print `PHASE scan: nothing to write` and skip to phase report.

3. **gate.** Run each of these in `$WT`, one command per call:
   - `uv run ruff format --check tools tests`
   - `uv run ruff check tools tests`
   - `uv run mypy`
   - `uv run pytest -q`
   - `uv run kb-lint --errors-only --diff-base origin/trunk`

   If one fails because of a file the scan wrote, revert that file and run the gates again.
   If a gate fails for any other reason, print `PHASE gate: FAILED <gate> <reason>` and push nothing.

4. **commit.**
   - Stage only the paths the skill's report lists, by name. Never use `git add -A` or `git add .`.
   - The subject is `docs: promote <N> harness additions`. The body lists every staged path, one per line.
   - The message must end with exactly this line: `Committed by Claude Code`
   - The pre-commit hook may bump `.claude/.claude-plugin/plugin.json`. Stage that bump and amend.

5. **push.**
   - Run `git push origin HEAD:trunk`.
   - If it is rejected, run `git fetch origin`, `git rebase origin/trunk`, the kb-lint gate, then push once more.
   - On a second rejection or a rebase conflict, print `PHASE push: FAILED <reason>` and keep the worktree.
   - Print `PHASE push: <short sha> <N> files`.

6. **report.** Print the skill's report, one line per item: files written, writes held back,
   issues filed, conflicts for `/kb-review`, and drops with reasons.

7. **cleanup.**
   - If the push succeeded or nothing was committed, run `git -C "$DB" worktree remove --force "$WT"`.
   - Print `PHASE cleanup: removed <path>`, `PHASE cleanup: kept <path> (unpushed commit)`, or `PHASE cleanup: FAILED <reason>`.
   - Never open a PR, force-push, or close an issue.
