---
name: np-core-contribute
description: Capture a new durable learning (rule, preference, plugin choice, environment quirk, useful command) into the correct nervepack file. Use when the user says "remember this in nervepack", "save to nervepack", "add this to my AI context", "save this to the team layer", or whenever you notice a fact worth keeping across sessions.
---

# np-core-contribute

The protocol for writing a new piece of context into nervepack so it survives
across sessions and machines.

## When to invoke

- Explicit user request: "remember this in nervepack", "save this", "add to nervepack"
- You notice a fact worth keeping: a stable preference, a non-obvious
  environment quirk, a useful command pattern, a recurring rule the user
  has stated twice or more
- After a substantial troubleshooting episode whose lesson would help future
  sessions

## Don't write to nervepack when

- The fact is session-scoped (current task, in-progress decision) — that
  belongs in the conversation, not the repo
- It's already documented in an existing skill (update instead of duplicate)
- It's a secret or credential
- It's project-specific — it belongs in that project's own `CLAUDE.md`

## First: which repo + layer?

Nervepack is split (`docs/ARCHITECTURE.md` § "Content seam"):

- **engine** (`~/Code/nervepack`) — machinery only, PII-clean: `np-core-*`/`np-flow-*`
  skills, `engine/setup/`, `agents/`, its own docs.
- **personal content overlay** — the default target for domain knowledge
  (`np-kb-*`/`np-env-*` skills, `wiki/`, `sources/`). Resolve it:
  `CONTENT="$(python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/np_content.py" content_dir)" || { echo "no content overlay resolved" >&2; exit 1; }`
  (single-repo layouts resolve to the engine root, so the same paths work).
  Check the exit status rather than assuming: `content_dir` exits 1 when it
  cannot resolve, and an unchecked `$CONTENT` is then empty, so every path built
  from it silently becomes a relative one rooted at the current directory.
- **team overlay** — only for a shared team convention ("save to the team layer",
  "this is a team rule", `--layer team`): resolve with `np_content.py team_dir` (same resolver).
  If that errors, STOP and tell the user the team layer isn't configured
  (`NP_TEAM_DIR` / `~/.config/nervepack/team-dir`) — never silently fall back to
  personal. Team overlays have the same shape; relink/index are team-aware.

`team.merge` governs read-time merging only; this gate controls *where the
write lands*. Below, `$REPO` = the root you picked.

## Decision tree: where does this go?

Classify the learning as one **kind**. The kind is the engine's vocabulary; the
*path* comes from the layer's own layout (step 3), never from this table.

| Kind of learning | Kind | Where |
|---|---|---|
| Personal coding rule | `skill` | extend `np-kb-coding-rules` |
| Environment / toolchain detail | `skill` | extend the matching `np-env-*` skill |
| Claude plugin choice or rationale | `skill` | extend `np-env-claude-plugin-stack` |
| New cross-cutting how-to the user will hit again | `skill` | a new skill (engine only for machinery) |
| Curated technical reference (version-pinned spec, RFC, official docs) | `reference` | **invoke ingest protocol** (see below) |
| Synthesis of a topic or concept | `knowledge` | pick the variant the layer declares |
| Recurring AI-agent prompt | `prompt` | the layer's prompt route |
| Bootstrap step (re-runnable) | — | Engine: `engine/setup/NN-name.sh` |
| Repo workflow / protocol | — | Engine: `CLAUDE.md` (this is the AI manual) |
| Roadmap / deferred-work item — for nervepack itself | `roadmap` | Engine: `docs/ROADMAP.md` |
| Roadmap / deferred-work item — for a pointed-to project (local-llm, pbrowne-net, …) | `roadmap` | that project's `ROADMAP.md` if it has one; else its `np-kb-<project>` pointer skill's **Roadmap** section (look + contribute there) |

When in doubt, prefer **editing an existing skill** over creating a new one.
Skills with overlapping descriptions are worse than one slightly bigger skill.

**Classify by layer first** — behavioral/how-to → a *skill*; knowledge → the
*wiki*; deferred work → a *roadmap row only* (a roadmap is not a knowledge
drawer). Cross-link related nodes across trees. Full rules, the skills-vs-
sources test, and the cross-tree lookup: references/classification.md

## Steps

Preflight for other writers (`git fetch && git status --short`) → sync first
([[np-core-sync]]) → branch off `origin/main` → check the merged INDEX for an overlapping
skill to extend instead of duplicating → resolve the target path via
`cli.py layout route` (never invent a directory) → write the update (run the
draft through [[np-flow-concise-output]]. Cross-reference another skill by
the target repo's own convention, never a relative file path (see
references/cross-reference-convention.md)) → guarantee an inbound
`[[wikilink]]` → new engine skill only: register it in `plugin.json` →
relink + regenerate INDEX → diff → commit (explicit paths, no LLM
attribution) → ask before pushing. Full 9-step recipe with commands:
references/steps.md

## Concurrency — both repos are one shared working tree

Other sessions and the crons write here too, and two crons commit to `skills/`
(`memory-promote` 08:00, `skill-maintain` 09:15).

**Standing preference: always branch, never write on `main`.** Sync first, branch off
`origin/main`, then commit on top. Branch even when the tree is clean. Do not rebase or
rewrite commits this session did not create, and leave another session's or a cron's
files and commits exactly where they are. The branch is what stops a diverged `main`,
or a cron's auto-split of the very skill being edited, from colliding with the write.
This overrides the older work-in-place-when-clean guidance in references/isolation.md.

Three rules that apply either way: commit with a **pathspec on `commit` as well as
`add`** (a bare `commit` takes the whole index), **check `INDEX.md` before staging it**
(it regenerates from every skill, so it absorbs another writer's uncommitted text),
and **re-read a `SKILL.md` from disk** before relying on it — a start-of-session
snapshot goes stale when another writer corrects the file.

Decision table, the `EnterWorktree` contract, and why relinking is hazardous from an
engine worktree but harmless from an overlay one: references/isolation.md

## Ingest protocol (when target is `sources/`)

If step 3 routes the contribution to `sources/<topic>/`, do not silently
write the file. Full steps: references/ingest-protocol.md

## Conflict policy

If the push is rejected as non-fast-forward:
1. `git -C "$REPO" pull --rebase --autostash`
2. If conflicts: surface them to the user; do not auto-resolve content
   conflicts in `SKILL.md` files (those are user intent).
3. Retry push.

## Size budget — keep skills lean

Soft cap: **~6 KB per `SKILL.md`**. Hard limit: 8 KB (enforced daily by
`engine/setup/np_skill_maintain.py`, dispatched via `cli.py cron skill-maintain`). Body carries the *decision*;
`references/*.md` carries the detail (read on demand).
Full guidance: references/size-budget.md

## Anti-patterns

- **Don't write to memory** (`~/.claude/projects/.../memory/`) for things
  that should live in nervepack. Memory is session-scoped; nervepack is durable.
- **Don't put domain knowledge in the engine.** `np-kb-*`/`np-env-*` skills,
  wiki, and sources belong in the content overlay; the engine is machinery-only
  and PII-clean.
- **Don't create a skill per fact.** Aggregate related facts into one skill.
- **Don't create a new skill without checking the merged INDEX.** Duplicates
  from parallel sessions are the failure mode this protocol exists to prevent.
- **Don't edit `archive/`** — that's the immutable history.
- **Don't include the user's email, tokens, or hostnames** in skills — those
  are environment-specific and should be parameterized or omitted.
