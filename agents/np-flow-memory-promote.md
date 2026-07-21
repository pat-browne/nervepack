# memory-promote

Local weekly task that promotes durable learnings out of the Claude memory
store (`~/.claude/projects/<your-project>/memory/`) and into `~/Code/nervepack`. Runs
as a user cron job — cloud agents can't see local memory, so this has to
stay local.

**Cadence:** Sunday 08:00 local (before the Sunday cloud `nervepack-refine`
fires at 09:00 — order matters because anything promoted here might be
something `nervepack-refine` lints next).

**Invoked by:** `engine/setup/np_agentic_cron.py` (`memory_promote()`, dispatched
via `cli.py cron memory-promote`; wraps `claude -p` and appends to
`~/.cache/nervepack/memory-promote.log`).

**Standing mandate:** pre-authorized to commit + push for the scope below.

---

## Prompt

You are a scheduled local task. You are running non-interactively via
`claude -p` — no human is watching. Do your work and exit. Don't ask
questions. If something blocks you, log it and stop.

Your job: triage Pat's Claude memory store and promote anything durable
into nervepack. Steps in order:

**Two repos (post content-cutover).** Personal skills + memory layers live in the
**content repo** (your cwd — `np_content_dir`, e.g. `~/Code/nervepack-content`): the
`np-kb-*`/`np-env-*` personal skills, `wiki/`, `memory/episodic/`. A promotion to a
**general engine skill** (a `np-core-*`/`np-flow-*` or a general `np-kb-*` that ships with
the engine) is committed in the **engine repo** (`$NERVEPACK` = `~/Code/nervepack`) instead
— flag in your report if you're unsure which a given entry belongs in.

### 1. Sync nervepack

```bash
~/Code/nervepack/engine/setup/40-sync-nervepack.sh --verbose
```

Read the resulting status. If it's anything other than `up to date` or
`fast-forwarded`, **stop**. Log "nervepack not in clean state — skipping
promotion" and exit. The next session can resolve.

### 2. Read the memory store

```bash
ls ~/.claude/projects/<your-project>/memory/*.md 2>/dev/null
```

For each file (except `MEMORY.md` itself, which is the index):

- Read it.
- Classify into one of three buckets:

  **Promote** — durable + machine-portable + would help future sessions on
  any project. Examples: a coding rule, an environment quirk, a stable
  preference, a plugin choice rationale.

  **Keep in memory** — session-scoped, machine-specific, time-bounded, or
  personal in a way that doesn't generalize. Examples: "current task is
  X", "we're mid-debugging Y", "remember Pat said he'd be back from PTO
  Thursday".

  **Stale** — references files/flags/projects/people that no longer
  exist. Verify against current state before deleting:
  ```bash
  # Example checks:
  test -d /path/from/memory || echo "path gone"
  grep -rl symbol_from_memory ~/some-repo || echo "symbol gone"
  ```

### 3. For each "promote" entry

Use the [[np-core-contribute]] decision tree to pick the right target file:

| Kind | Target |
|---|---|
| Personal coding rule | `$NP_CONTENT_DIR/skills/np-kb-coding-rules/SKILL.md` (personal overlay) |
| Environment / toolchain | `skills/np-env-ubuntu-claude-dev-setup/SKILL.md` |
| Claude plugin choice | `skills/np-env-claude-plugin-stack/SKILL.md` |
| New cross-cutting topic | Check `INDEX.md` first — extend an existing skill if any overlap |
| Setup step | New `engine/setup/NN-name.sh` |

**Check `INDEX.md` before creating any new skill.** Extend over create.

Make the edit, then:
- Delete the memory file: `rm ~/.claude/projects/<your-project>/memory/<name>.md`
- Remove its line from `~/.claude/projects/<your-project>/memory/MEMORY.md`

### 4. For each "stale" entry

- Delete the file
- Remove its line from `MEMORY.md`

### 5. Regenerate INDEX and commit

```bash
~/Code/nervepack/engine/setup/30-link-skills.sh   # relinks both trees + regenerates INDEX.md (in the engine)
```

Commit to the repo each change actually landed in (two repos — see the note at
the top). Set the identity the same way in whichever repo(s) you touch:

```bash
# Author as the repo's configured git identity — never a bot name. `git config` without --global persists in
# .git/config and mis-authors later interactive commits (CLAUDE.md § Commit conventions).
# Commit identity: use the runner's existing git config; if unset (headless/cloud),
# fall back to NP_GIT_AUTHOR_* env, then a neutral bot. (Pat sets NP_GIT_AUTHOR_* in his
# cloud routine config to keep his attribution; a fork gets the fork-runner's identity.)
ident() { git -C "$1" config user.email >/dev/null 2>&1 || git -C "$1" config user.email "${NP_GIT_AUTHOR_EMAIL:-nervepack-agent@localhost}"; git -C "$1" config user.name >/dev/null 2>&1 || git -C "$1" config user.name "${NP_GIT_AUTHOR_NAME:-nervepack agent}"; }
```

**Personal-skill / memory-layer promotions** (the common case) land in the **content
repo** = your cwd:

```bash
CONTENT="$(pwd)"   # = np_content_dir
ident "$CONTENT"
# Stage AND commit ONLY the paths you changed — CLAUDE.md forbids `git add -A`/`.`/`-am`
# AND a pathspec-less `commit` (a bare commit re-commits the whole index, sweeping a
# concurrent session's staged work — issue #11). Path-limit BOTH `add` and `commit`.
git -C "$CONTENT" add skills wiki   # + only the layer dirs you actually wrote
git -C "$CONTENT" commit -m "promote: weekly memory→content ($(date -u +%F))" \
  -m "Promoted <N> entries:
- <name> → <target-file>" \
  -- skills wiki   # same explicit paths — never a bare commit
git -C "$CONTENT" push
```

**A promotion to a GENERAL engine skill** (a `np-core-*`/`np-flow-*` or a general
`np-kb-*` that ships with the engine) lands in the **engine repo** instead:

```bash
NP="$HOME/Code/nervepack"
ident "$NP"
git -C "$NP" add skills INDEX.md .claude-plugin/plugin.json   # the engine-side paths you changed
git -C "$NP" commit -m "promote: weekly memory→engine ($(date -u +%F))" -m "- <name> → <target>" \
  -- skills INDEX.md .claude-plugin/plugin.json   # path-limit the commit too (issue #11)
git -C "$NP" push
```

`30-link-skills.sh` regenerates `INDEX.md` in the engine, so stage `INDEX.md` only in
the engine commit. If nothing changed: exit silently. No empty commits.

### 6. Report

Print one short summary (it lands in the log):

- Promoted: count + brief list (memory-name → target-skill)
- Kept: count (no list — those are session-scoped by definition)
- Stale: count + brief list
- Anything notable (e.g. "couldn't classify <name> — left it alone")

Scope ends here. Don't lint, don't dedup, don't compact — those are
covered by `nervepack-refine` and `nervepack-compact` cloud agents.
