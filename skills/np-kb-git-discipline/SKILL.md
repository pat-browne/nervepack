---
name: np-kb-git-discipline
description: Git branching/commit discipline for every repo — never commit directly to main/master/trunk; always work on a feature branch and land via PR. Use whenever you are about to commit, when capturing a learning into nervepack, when dispatching subagents that may commit, or when an accidental commit lands on a protected branch. Covers the rewind procedure and the worktree+subagent base-branch hazard.
---

# Git discipline — never commit directly to a protected branch

**The rule (all repos, no exceptions):** never commit directly to `main`,
`master`, or `trunk`. Create a feature branch first, commit there, and land the
work through a **pull request**. This holds for code repos *and* for the nervepack
engine / content overlays — durable captures go on a branch → PR too.

> This **supersedes** the "commit to main and push" step in [[np-core-contribute]]:
> still write the learning into the right file, but commit it on a branch and open a
> PR — do not commit it onto the overlay's `main`.

## Before any commit, check the branch

```bash
git branch --show-current   # if this is main/master/trunk → STOP, branch first
git switch -c <type>/<short-name>   # e.g. learnings/source-from-data-requests
```

Only then `git add`/`git commit`. Push and PR when the user asks (see
[[np-core-contribute]] § push gate — push still requires confirmation).

## If a commit already landed on a protected branch

Rewind it before it propagates — do **not** push:

- Keep the changes, drop the commit: `git reset --mixed HEAD~1` (work stays in the
  working tree; re-commit it on a branch).
- Then branch and re-commit: `git switch -c <type>/<name>` → `git add <files>` →
  `git commit`.

Never `--hard`-reset a protected branch to "fix" this unless the content is
provably safe elsewhere (e.g. already on the PR branch), and confirm with the user
first — rewinding a shared branch is destructive.

## Worktree + subagent hazard (how accidental main commits happen)

A subagent dispatched while you work in a git **worktree** can run in the **main
checkout** instead of the worktree, and commit to the base branch (`trunk`) rather
than the feature branch. Guard against it:

- Pin/verify the subagent's working directory — pass the worktree path explicitly
  and have the subagent print `pwd` + `git branch --show-current` before committing.
- After a subagent reports a commit, verify it landed on the **feature branch**
  (`git log --oneline -1` in the worktree), not on `trunk` in the main checkout.
- If it landed on the base branch, apply the rewind procedure above (cherry-pick the
  commit onto the feature branch, then rewind the protected branch with confirmation).

## Why

Direct-to-main commits skip review, entangle with others' in-flight work, and on a
shared/origin branch are hard to undo. Branch + PR keeps every change reviewable and
reversible, and keeps protected branches matching their remote.
