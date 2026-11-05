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
   - Create `WT=$DB/../data-base-promote-scan-$DATE` with `git -C "$DB" worktree add --detach "$WT" origin/trunk`. If it already exists, print `PHASE setup: FAILED worktree exists, see Manual recovery`. If the command fails for another reason, print `PHASE setup: FAILED worktree add <error>`.
   - Confirm `.claude/skills/harness-promote-scan/SKILL.md` exists in `$WT`. If not, print `PHASE setup: FAILED harness-promote-scan skill missing on trunk`.
   - Run `uv sync --all-extras --dev` in `$WT`. If it fails, print `PHASE setup: FAILED uv sync <error>`.
   - Never touch the main `$DB` checkout. Run every later step inside `$WT`.
   - Print `PHASE setup: ok <WT path>`.

2. **scan.**
   - Read `.claude/skills/harness-promote-scan/SKILL.md` in `$WT` and follow it exactly. Do not modify it.
   - Take the counts, paths and URLs from the skill's step 7 report. Print `PHASE scan: wrote <N> files, filed <M> issues <urls>`.
   - If `PROMOTE_DRY_RUN=1`, print the skill's plan, skip phases gate, commit and push, and go to phase report.
   - If `git status --porcelain` is empty, print `PHASE scan: nothing to write`, skip phases gate, commit and push, and go to phase report.

3. **gate.** First check the scope of every changed path. Use `git status --porcelain` and
   `git diff --numstat origin/trunk`, not the skill's word.
   - Delete each new file the report lists under `lint-failed`.
   - A path outside `docs/` and `.claude/skills/<name>/` for an existing skill is out of scope.
   - A new file under `.claude/skills/` is out of scope. New skills go through issues.
   - Any path under `.claude/skills/harness-promote-scan/` is out of scope. The scan never edits itself.
   - A file is out of scope if an added line matches a secret pattern: `AccountKey=`, `Password=`, `SharedAccessSignature`, `-----BEGIN`, `ghp_`, `xox`, `AKIA`, or a GUID.
   - A changed skill file is out of scope if it deletes any line, or adds more than `PROMOTE_LARGE_SKILL_LINES` (default 40) lines.
   - A changed `SKILL.md` is out of scope if `git diff` touches its frontmatter.
   - Restore each out-of-scope tracked file with `git checkout origin/trunk -- <path>`. Delete each out-of-scope new file.
   - Print `PHASE gate: dropped <path> <reason>` for each one.

   Then run each of these in `$WT`, one command per call:
   - `uv run ruff format --check tools tests`
   - `uv run ruff check tools tests`
   - `uv run mypy`
   - `uv run pytest -q`
   - `uv run kb-lint --errors-only --diff-base origin/trunk`

   Wrap each command in `timeout 900` (`gtimeout` on macOS, skip the wrap if neither exists). A timeout is a gate failure.
   If a gate's output names a file the scan wrote, restore it with `git checkout origin/trunk -- <path>` or delete it if new. Then run all gates again, at most twice.
   If the failure names no scan file, treat it as the other case below.
   If a gate fails for any other reason, print `PHASE gate: FAILED <gate> <reason>` and push nothing.

4. **commit.**
   - Stage only the paths the skill's report lists, by name. Never use `git add -A` or `git add .`.
   - The subject is `docs: promote <N> harness additions`, where N counts the paths staged after the gate. The body lists every staged path, one per line.
   - The message must end with exactly this line: `Committed by Claude Code`
   - The pre-commit hook may bump `.claude/.claude-plugin/plugin.json`. If `git status --porcelain` then shows it, stage it and run `git commit --amend --no-edit`. If the amend fails, print `PHASE commit: FAILED amend <error>`.

5. **push.**
   - Run `git push origin HEAD:trunk`.
   - If it is rejected, run `git fetch origin`, `git rebase origin/trunk`, the kb-lint gate, then push once more. If that kb-lint fails, print `PHASE push: FAILED kb-lint after rebase` and push nothing.
   - On a second rejection, print `PHASE push: FAILED rejected twice`. On a rebase conflict, run `git rebase --abort` and print `PHASE push: FAILED rebase conflict <paths>`. Keep the worktree in both cases.
   - Print `PHASE push: <short sha> <N> files`.

6. **report.** Print the skill's report, one line per item: files written, writes held back,
   issues filed, conflicts for `/kb-review`, and drops with reasons.

7. **cleanup.**
   - If the push succeeded or `git log origin/trunk..HEAD` is empty, run `git -C "$DB" worktree remove --force "$WT"`.
   - Print `PHASE cleanup: removed <path>`, `PHASE cleanup: kept <path> (unpushed commit)`, or `PHASE cleanup: FAILED <reason>`.
   - Never open a PR, force-push, or close an issue.
