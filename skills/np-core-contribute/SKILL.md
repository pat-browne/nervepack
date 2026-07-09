---
name: np-core-contribute
description: Capture a new durable learning (rule, preference, plugin choice, environment quirk, useful command) into ~/Code/nervepack in the correct file, then commit and push. Use when the user says "remember this in nervepack", "save to nervepack", "add this to my AI context", or whenever you notice a fact worth keeping across sessions, or "save this to the team layer".
---

# np-core-contribute

The protocol for writing a new piece of context into `~/Code/nervepack` so it survives
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

## First: which layer?

Most contributions go to your **personal** overlay (the default). Write to the
**team** overlay instead when the learning is a shared team convention — triggered by
"save to the team layer", "this is a team rule", "contribute to the team", or an explicit
`--layer team`.

- **personal** (default): the write/commit steps below target `~/Code/nervepack` (engine)
  or your personal content overlay, exactly as today.
- **team**: resolve the team overlay root with `TEAM="$(cd ~/Code/nervepack && source engine/setup/np-content-lib.sh && np_team_dir)"`.
  If that errors (no team layer configured), STOP and tell the user the team layer isn't
  set up (`NP_TEAM_DIR` / `~/.config/nervepack/team-dir`) — do not silently fall back to
  personal. Otherwise run the same write + `git -C "$TEAM" add/commit/push` steps against
  `$TEAM` instead of `~/Code/nervepack`. The team overlay has the same shape
  (`skills/`, `wiki/`, …); skill relink/index regeneration is already team-aware.

`team.merge` governs how a team entry combines with a personal one at *read* time; this
gate only controls *where the write lands*.

## Decision tree: where does this go?

| Kind of learning | Target file |
|---|---|
| Personal coding rule | `skills/np-kb-coding-rules/SKILL.md` |
| Environment / toolchain detail | `skills/np-env-ubuntu-claude-dev-setup/SKILL.md` |
| Claude plugin choice or rationale | `skills/np-env-claude-plugin-stack/SKILL.md` |
| New cross-cutting skill (behavior) | New dir: `skills/<kebab-name>/SKILL.md` |
| Curated technical reference doc (version-pinned spec, RFC, official docs) | `sources/<topic>/<name>.md` — **invoke ingest protocol** (see below) |
| Reusable how-to / capability the user will hit again (e.g. "how to build a persona agent") | New behavioral skill: `skills/<kebab-name>/SKILL.md` |
| Curated synthesis of a topic backed by sources | `wiki/topics/<topic>/<topic>.md` (`kind: topic`) |
| Source-free synthesis of one entity/concept (a specific build, a cross-cutting idea) | `wiki/concepts/<name>.md` (`kind: concept`) |
| Bootstrap step (re-runnable) | New script: `engine/setup/NN-name.sh` |
| Repo workflow / protocol | `CLAUDE.md` (this is the AI manual) |
| Recurring AI-agent prompt | `agents/<name>.md` |
| Roadmap / deferred-work item — for nervepack itself | `docs/ROADMAP.md` |
| Roadmap / deferred-work item — for a pointed-to project (local-llm, pbrowne-net, …) | that project's `ROADMAP.md` if it has one; else its `np-kb-<project>` pointer skill's **Roadmap** section (look + contribute there) |

When in doubt, prefer **editing an existing skill** over creating a new one.
Skills with overlapping descriptions are worse than one slightly bigger skill.

### Classify by LAYER before you capture (anti-drawer rule)

Decide *what kind of thing* the learning is **before** picking a file:

- **Behavioral / how-to** (a reusable technique, rule, or capability) → a **skill**
  (new one if it's worth a name — not a paragraph buried elsewhere).
- **Knowledge** (what a thing is, how a build works, a synthesized topic) → the
  **wiki** (`concepts/` or `topics/`).
- **Deferred work** (not done yet, revisit on a trigger) → a **roadmap** row only.

A roadmap (incl. `references/roadmap.md`) is **deferred-work tracking, not a
knowledge drawer** — even for a roadmap item, the deferred line goes in the
roadmap and the durable how-to/detail goes in a skill or wiki page, cross-linked.
(Miss: the Walter persona how-to was dumped in the local-llm roadmap, then split
out to [[np-kb-persona-llm-agents]] + wiki. Classify first, skip the rework.)

### Skills vs sources — which layer?

- **Skill** = "how to act / what's installed / what to prefer." Behavioral
  guidance, opinion, choice. User-specific.
- **Source** = "what the spec says." Official reference content, version-
  pinned, defer-first when answering. Not opinionated — quotes/excerpts
  the canonical document.
- Cross-link them in a `wiki/` synthesis page when the entity (e.g. Rust)
  has both skill content *and* source content.

### Cross-tree linking — look before you author

Durable docs favor links over duplication. Beyond the same-topic dup check in
step 2, do a **lightweight cross-tree lookup**: grep `INDEX.md` / `wiki/` /
`sources/` for the subject matter you are documenting. If a related node lives
in a *different* tree — even with zero duplication risk — add a `[[wikilink]]`
(or path) so a future agent can navigate to it. Depth lives in one place and is
linked from everywhere else, never copied (see `docs/ARCHITECTURE.md`).

## Steps

1. **Sync first.** Invoke [[np-core-sync]] to avoid creating a fork.
2. **Check INDEX.md before writing.** This is the single most important
   step for avoiding duplicate skills from disparate sessions/repos:
   ```bash
   cat ~/Code/nervepack/INDEX.md
   ```
   For the learning you're about to write, identify keywords (the topic,
   the trigger conditions, the kind of artifact). Grep/scan the INDEX
   descriptions for those keywords. If any existing skill scores meaningful
   overlap (same topic, overlapping "use when…" triggers, or similar
   artifact class), **extend that skill** instead of creating a new one.
   When in doubt between extend-vs-create, prefer extend.
3. **Pick the target** using the decision table above (or the existing
   skill identified in step 2).
4. **Write the update.** For an existing skill: minimal surgical edit. For
   a new skill: include `---` frontmatter with `name:` and `description:`.
   The description must say WHAT it teaches and WHEN to use it — specific
   enough that step 2 will work for the next contributor.
5. **Update `.claude-plugin/plugin.json`** if you added a new skill —
   append `./skills/<name>` to the `skills` array.
6. **Relink + regenerate INDEX:** `~/Code/nervepack/engine/setup/30-link-skills.sh`
   (handles new skills, prunes dangling symlinks, and re-runs
   `60-generate-index.sh`).
7. **Diff:** `git -C ~/Code/nervepack diff` — show the user.
8. **Commit** with conventional subject (see `CLAUDE.md` § "Commit conventions"):
   ```bash
   git -C ~/Code/nervepack add -A
   git -C ~/Code/nervepack commit -m "skill(<name>): <what changed>"
   ```
   No LLM attribution trailer — see `AGENTS.md` § "Commit conventions".
9. **Ask before pushing.** Push is the action that affects another machine.
   Default to `git -C ~/Code/nervepack push` only after the user confirms — unless
   they've said "auto-push" or this run was invoked from a scheduled agent
   (which has a standing mandate; see `agents/np-flow-scheduled-refine.md` and
   `agents/np-flow-weekly-compact.md`).

## Ingest protocol (when target is `sources/`)

If step 3 routes the contribution to `sources/<topic>/`, do not silently
write the file. Full steps: references/ingest-protocol.md

## Conflict policy

If the push is rejected as non-fast-forward:
1. `git -C ~/Code/nervepack pull --rebase --autostash`
2. If conflicts: surface them to the user; do not auto-resolve content
   conflicts in `SKILL.md` files (those are user intent).
3. Retry push.

## Size budget — keep skills lean

Soft cap: **~6 KB per `SKILL.md`**. Hard limit: 8 KB (enforced daily by `engine/setup/75-skill-maintain.sh`).
Body carries the *decision*; `references/*.md` carries the detail (read on demand).
Full guidance: references/size-budget.md

## Anti-patterns

- **Don't write to memory** (`~/.claude/projects/.../memory/`) for things
  that should live in nervepack. Memory is session-scoped; nervepack is durable.
- **Don't create a skill per fact.** Aggregate related facts into one skill.
- **Don't create a new skill without checking INDEX.md.** Duplicates from
  parallel sessions are the failure mode this protocol exists to prevent.
- **Don't edit `archive/`** — that's the immutable history.
- **Don't include the user's email, tokens, or hostnames** in skills — those
  are environment-specific and should be parameterized or omitted.
