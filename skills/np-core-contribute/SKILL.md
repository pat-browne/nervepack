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
  `CONTENT="$(source ~/Code/nervepack/engine/setup/np-content-lib.sh && np_content_dir)"`
  (single-repo layouts resolve to the engine root, so the same paths work).
- **team overlay** — only for a shared team convention ("save to the team layer",
  "this is a team rule", `--layer team`): resolve with `np_team_dir` (same lib).
  If that errors, STOP and tell the user the team layer isn't configured
  (`NP_TEAM_DIR` / `~/.config/nervepack/team-dir`) — never silently fall back to
  personal. Team overlays have the same shape; relink/index are team-aware.

`team.merge` governs read-time merging only; this gate controls *where the
write lands*. Below, `$REPO` = the root you picked.

## Decision tree: where does this go?

| Kind of learning | Target |
|---|---|
| Personal coding rule | `$CONTENT/skills/np-kb-coding-rules/SKILL.md` |
| Environment / toolchain detail | `$CONTENT/skills/np-env-ubuntu-claude-dev-setup/SKILL.md` |
| Claude plugin choice or rationale | `$CONTENT/skills/np-env-claude-plugin-stack/SKILL.md` |
| New cross-cutting skill / reusable how-to the user will hit again | `$CONTENT/skills/<kebab-name>/SKILL.md` (engine only for new machinery skills) |
| Curated technical reference doc (version-pinned spec, RFC, official docs) | `$CONTENT/sources/<topic>/<name>.md` — **invoke ingest protocol** (see below) |
| Curated synthesis of a topic backed by sources | `$CONTENT/wiki/topics/<topic>/<topic>.md` (`kind: topic`) |
| Source-free synthesis of one entity/concept (a specific build, a cross-cutting idea) | `$CONTENT/wiki/concepts/<name>.md` (`kind: concept`) |
| Bootstrap step (re-runnable) | Engine: `engine/setup/NN-name.sh` |
| Repo workflow / protocol | Engine: `CLAUDE.md` (this is the AI manual) |
| Recurring AI-agent prompt | Engine: `agents/<name>.md` |
| Roadmap / deferred-work item — for nervepack itself | Engine: `docs/ROADMAP.md` |
| Roadmap / deferred-work item — for a pointed-to project (local-llm, pbrowne-net, …) | that project's `ROADMAP.md` if it has one; else its `np-kb-<project>` pointer skill's **Roadmap** section (look + contribute there) |

When in doubt, prefer **editing an existing skill** over creating a new one.
Skills with overlapping descriptions are worse than one slightly bigger skill.

**Classify by layer first** — behavioral/how-to → a *skill*; knowledge → the
*wiki*; deferred work → a *roadmap row only* (a roadmap is not a knowledge
drawer). Cross-link related nodes across trees. Full rules, the skills-vs-
sources test, and the cross-tree lookup: references/classification.md

## Steps

1. **Sync first.** Invoke [[np-core-sync]] to avoid creating a fork.
2. **Check the merged INDEX before writing.** The single most important step
   for avoiding duplicate skills from disparate sessions/repos:
   ```bash
   cat "$CONTENT/INDEX.md"   # merged engine+overlay index (engine INDEX.md lists engine skills only)
   ```
   Scan the descriptions for your topic / trigger / artifact keywords. If an
   existing skill overlaps meaningfully (same topic, overlapping "use when…"
   triggers, or similar artifact class), **extend that skill** instead of
   creating a new one. When in doubt, prefer extend.
3. **Pick the target** using the decision table above (or the existing
   skill identified in step 2).
4. **Write the update.** For an existing skill: minimal surgical edit. For
   a new skill: include `---` frontmatter with `name:` and `description:`.
   The description must say WHAT it teaches and WHEN to use it — specific
   enough that step 2 will work for the next contributor.
5. **New engine skill only:** append `./skills/<name>` to the `skills` array
   in the engine's `.claude-plugin/plugin.json`. Overlay skills are picked up
   by the relink alone.
6. **Relink + regenerate INDEX:** `~/Code/nervepack/engine/setup/30-link-skills.sh`
   (handles new skills in every layer, prunes dangling symlinks, and re-runs
   `60-generate-index.sh`).
7. **Diff:** `git -C "$REPO" diff` — show the user.
8. **Commit** with conventional subject (see `AGENTS.md` § "Commit conventions"),
   staging explicit paths (never `-A` — a cron or second session may share the tree):
   ```bash
   git -C "$REPO" add <changed paths>
   git -C "$REPO" commit -m "skill(<name>): <what changed>"
   ```
   No LLM attribution trailer — see `AGENTS.md` § "Commit conventions".
9. **Ask before pushing.** Push is the action that affects another machine.
   Default to `git -C "$REPO" push` only after the user confirms — unless
   they've said "auto-push" or this run was invoked from a scheduled agent
   (which has a standing mandate; see `agents/np-flow-scheduled-refine.md` and
   `agents/np-flow-weekly-compact.md`).

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
