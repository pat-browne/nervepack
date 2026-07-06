---
name: np-kb-git-gotchas
description: Gotchas when committing/inspecting changes with git via a shell (esp. the Bash tool) that lead to wrong commits or wrong conclusions. Chiefly — a file MOVE split across two commits is NOT detected as a rename, so a `D old/path` in `git status` can be a move (content still exists elsewhere), not a deletion; and backticks/`$(...)` inside a double-quoted `git commit -m "..."` trigger shell command substitution and silently mangle the message. Use before writing a commit message that says "deleted/removed/retired", before `git add -A` in a dirty/reorg tree, or when a commit message came out garbled.
---

# Git gotchas (committing & inspecting via a shell)

Two traps that produce a *wrong commit* or a *wrong conclusion* — both bit real
sessions.

## 1. A move split across commits is NOT a rename — `D old/path` may be a move

Git only detects a rename when the delete of the old path and the add of the new
path are **in the same diff**. If an earlier commit already added `new/path`
(e.g. someone nested files under a subfolder) and your working tree just has the
old copies pending deletion, `git status` shows a bare `D old/path` — which looks
like the content is *gone*. It isn't; it lives at `new/path`.

**Before writing a commit message that says "deleted / removed / retired", verify
the content didn't just move:**
- `grep -rl "<distinctive string or basename>" .` (or `git ls-files '*<basename>*'`)
  — does the file/content exist under another path?
- `git log --oneline -- <new/path>` — was it added in a prior commit?
- Review with rename detection: `git show <commit> -M --summary`, or
  `git diff -M`. (Across separate commits, `-M` still won't link them — so the
  grep check is the reliable one.)

Real miss: a tree had `D erd-*.md` at the top level; the files had been nested
under `sql-server/` in an earlier commit. A commit message claiming the pages
were "retired" was wrong — they were just moved, and name-based `[[wikilinks]]`
to them still resolved. Also: don't reflexively `git add -A` a dirty reorg tree
without understanding whether deletions are moves — and never sweep in `.DS_Store`
/ scratch files (gitignore them first).

## 2. Backticks / `$(...)` in `git commit -m "…"` run command substitution

A **double-quoted** shell string performs command substitution. So:

```bash
git commit -m "add `schema` override"    # `schema` is EXECUTED → "command not found: schema"
                                          # → commit body becomes "add  override" (word eaten)
```

Symptoms: a stray `command not found: X` in the output, and a word silently
missing from the committed message. Backticks, `$(…)`, and bare `$VAR` are all
interpolated inside double quotes.

**Fix: single-quote commit messages** (and any literal shell string containing
`` ` ``, `$`, or `\`):

```bash
git commit -m 'add `schema` override'    # literal; backticks preserved
```

For multi-paragraph messages, prefer single-quoted `-m` (or several `-m` flags,
one per paragraph). If the text must contain a single quote, use `$'...'` or a
heredoc-fed `-F -`. Verify with `git log -1 --format=%B` when in doubt.

## Related
- [[np-flow-merge-gate]] — coordinating a merge when another agent/cron shares the repo.
- [[np-kb-coding-rules]] §6 — commit as the repo identity, no LLM attribution trailers.
