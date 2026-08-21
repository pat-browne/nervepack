# np-core-sync — per-outcome steps

### `up to date`
Report and stop.

### `fast-forwarded N commit(s)`
Show the user `git -C ~/Code/nervepack log <prev>..HEAD --oneline` so they see what
landed. The linker already ran inside the script, and (as of #106) so has every
`5[0-9]-install-*.sh` hook installer — a pulled change to a hook's registered
command (e.g. a stdout/stderr redirect fix) reaches `~/.claude/settings.json` in
the same sync, not on some later manual re-install. No further action.

### `local is N ahead`
**No direct push to main — every push goes through a PR.** (Superseded
2026-08-13: the prior standing preference auto-pushed already-committed local
state straight to `origin/main`. That is gone.) Show the unpushed commits
(`git -C ~/Code/nervepack log @{u}..HEAD --oneline`), then create a branch,
push it, and open a PR:
```bash
git -C ~/Code/nervepack checkout -b sync/<short-sha>-<date>
git -C ~/Code/nervepack push -u origin sync/<short-sha>-<date>
gh pr create --repo <owner>/nervepack --fill
```
Report the PR URL. If already on a feature branch (not `main`) with an
upstream, just push it and open the PR from there — no need to branch again.
If `gh` is missing, unauthenticated, or the push is rejected: degrade to the
old plain report ("N commits ahead — not pushed") and surface the specific
failure; never fall back to a direct push. **This only ever happens here**,
in this skill's own interactive steps — never from the background
`SessionStart` hook, which has no model in the loop to make this call and
keeps today's passive report-only behavior for engine, team, and content
layers alike.

### `SKIPPED (dirty)`
Run `git -C ~/Code/nervepack status --short`. Show the user. Suggest the right next
step based on intent:
- "I'm done with these changes" → invoke [[np-core-contribute]] to commit + push
- "I'm not done" → suggest `git -C ~/Code/nervepack stash`, then re-run sync, then
  `git stash pop`

### `DIVERGED`
Surface both sides:
```bash
git -C ~/Code/nervepack log @{u}..HEAD --oneline       # local-only commits
git -C ~/Code/nervepack log HEAD..@{u} --oneline       # remote-only commits
```
Do NOT auto-resolve. Ask the user how to proceed. Defaults:
- If the divergence is just lint/format from the cron agent on files the
  user also edited → `git -C ~/Code/nervepack pull --rebase --autostash` and walk
  conflicts with the user.
- If the divergence is a real edit collision → consider whether the user
  wants to keep both sides; surface the diffs.

**Check the local-only side before calling it noise.** Local-only commits on
`main` are not always leftover work from someone else. Read each one with
`git show <sha> --stat`. A commit dated within the last 7 days, with a
message that names a feature rather than a merge artifact, is a candidate for
this session's own finished, unpushed work. Cross-check it against open
issues with `gh issue list` or `gh issue view <n>` before deciding.

If it turns out to be real, unpushed work: treat local `main` itself as the
source, not the target. Branch from it, push the branch, and open a PR, the
same as the `local is N ahead` case above:
```bash
git -C ~/Code/nervepack checkout -B recover/<short-sha>-<date> <local-sha>
git -C ~/Code/nervepack push -u origin recover/<short-sha>-<date>
gh pr create --repo <owner>/nervepack --fill
```
Never `git push origin <sha>:refs/heads/main` directly. That bypasses the PR
gate this same skill enforces for the ordinary `local is N ahead` case, and a
diverged `main` means the safety that gate exists for is exactly what is
missing right now.

**Re-check issue and PR state before trusting a plan doc's last snapshot.**
Remote-only commits can represent an entire wave of a tracked epic landing
through a concurrent agent or session while this one was away. A plan doc
written even a day earlier can be stale in a way `git log` alone will not
flag. Confirm against `gh issue view <n>` before reporting a wave as still
open or resuming "next" work on it.
