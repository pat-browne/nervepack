# Concurrency: writing to a repo other writers share

> **Superseded in part.** The standing preference is now: always sync first, always
> branch off `origin/main`, always commit on top, and never rewrite or move commits
> and files this session did not create. The work-in-place-when-clean option below is
> no longer offered. Read the rest for the mechanics, not for the choice.

Both nervepack repos are **single working trees with one git HEAD**, and several
writers touch them without asking: other interactive sessions, background and cloud
sessions, and the scheduled crons. Two of those crons commit to `skills/` —
`memory-promote` (daily 08:00) promotes memory entries into skills, and
`skill-maintain` (daily 09:15) rewrites any `SKILL.md` over the 8 KB budget and
creates `references/` under it. `episodic-maintain` (08:30) owns `memory/`, and the
metrics aggregator owns `dashboard/data/`.

`AGENTS.md` § "When another AI session may be working in this repo concurrently"
holds the repo-level protocol. It only loads for a session started **in** the engine
directory, and contribute runs from anywhere, so the parts that protect a
contribution are restated here.

## Preflight, every time

```bash
git -C "$REPO" fetch --quiet
git -C "$REPO" status --short          # who else is mid-edit
```

Then pick the cheapest option that holds:

| Tree state | Do this |
|---|---|
| Clean | Work in place. Pathspec-limited commit (below) is still mandatory. |
| Dirty, but not in a path you will touch | Work in place. Stage and commit explicit paths. Do not commit a regenerated `INDEX.md` without checking it (below). |
| Dirty in a path you intend to edit | **Isolate.** Another writer holds uncommitted work in your target file. |
| You are a background / cloud session, or the edit spans several files | **Isolate.** |

## Three failure modes worth naming

**Staging and commit contamination.** `git add -A` sweeps another writer's untracked
files. Less obviously, a **bare `git commit` after an explicit `git add` still
commits the whole index**, so it captures whatever another session staged. The `add`
scope is lost the moment a pathspec-less `commit` runs. Always:

```bash
git -C "$REPO" add <paths>
git -C "$REPO" commit -m "skill(<name>): <what changed>" -- <paths>
```

**Generated-file contamination.** `cli.py setup link-skills` regenerates `INDEX.md`
from **every** skill in the tree, so running it while another writer has uncommitted
description or body edits bakes their in-progress state into your commit. After
regenerating, check before staging:

```bash
git -C "$REPO" diff -- INDEX.md      # expect only your own rows to move
```

If it carries someone else's rows, either isolate, or leave `INDEX.md` unstaged and
say so — a stale index is recoverable, a commit misattributing another writer's text
is not.

**Stale reads.** A `SKILL.md` snapshot injected at SessionStart, or read early in a
long session, goes stale when another writer corrects the file. Re-read the file from
disk before you rely on it for anything load-bearing. Cost of learning this: a
session built and published an architectural claim on a start-of-session snapshot
whose correction had already landed on disk hours earlier.

## Isolating

`EnterWorktree` is the harness path. Its own contract says to use it only when the
user or project instructions direct it — **this skill is that instruction**, so a
contribute flow may invoke it without further permission. It defaults to
`baseRef: fresh` (branches from `origin/<default-branch>`), which also removes the
stale-read problem, since you start from committed state rather than a contaminated
tree. Plain `git worktree add ../<repo>-wt <branch>` works the same way.

Then: edit → pathspec-limited commit in the worktree → merge back → **relink in the
main checkout**.

### Two verified sharp edges, and they differ per repo

`np_link_skills.py` resolves its two roots differently, so a worktree behaves
asymmetrically depending on which repo you isolated:

- **Content-overlay worktree.** The content root comes from
  `np_content.content_dir()` — the *configured* path, not the tree you are running
  in. So `link-skills` ignores your worktree completely: your new skill is not
  linked into the host's skill dir and not in `INDEX.md` until you merge into the
  configured checkout and relink **there**. Harmless, as long as you do not expect
  the skill to be live while you are still in the worktree.
- **Engine worktree.** `engine_root` is derived from the running file's own repo
  root. Running `link-skills` from an engine worktree therefore points every
  `~/.claude/skills/*` symlink **into the worktree**, and they all break the moment
  it is removed. **Never run `link-skills` from an engine worktree.** Merge first,
  then relink from the primary checkout.

`INDEX.md` conflicts on merge nearly every time, because both sides regenerated it.
Never hand-merge it: take either side, then rerun `link-skills` to regenerate.

## Engine changes are a PR, not a push

The engine repo is public. Changes under `dashboard/`, `engine/`, and the
`np-core-*`/`np-flow-*` skills go through a PR that merges only on green CI, never
direct to main. Keep engine commit messages and PR bodies company-neutral. The
private content overlay has no CI gate and may be pushed directly.

Related: [[np-flow-merge-gate]] for waiting on concurrent work before merging, and
[[np-kb-git-gotchas]] for the recovery paths when a shared tree has already bitten
you.
