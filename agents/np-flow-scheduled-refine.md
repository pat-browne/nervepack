# scheduled-refine

The recurring remote-agent prompt for refining `pat-browne/nervepack`. Configured
via the `schedule` skill (or `claude schedule create`) to run weekly.

**Cadence:** weekly (Sunday 09:00 America/Denver = `0 15 * * 0` UTC during
MDT; will fire at 08:00 local during MST — accept the half-year drift in
exchange for not having to handle DST in cron).

**Where this runs:** Anthropic's cloud (CCR), NOT the user's local machine.
The agent receives a fresh clone of the repo as its working directory. It
has no access to Pat's local `~/Code/nervepack`, `~/.claude/skills/`, or
`~/.claude/projects/.../memory/`.

**Standing mandate (referenced by [[np-core-contribute]]):**
Pre-authorized to commit + push for the scope below. No per-run confirmation.

**Companion local task:** memory-store → skills promotion happens *locally*
via `/loop` invocations of [[np-core-contribute]] — it requires access to
`~/.claude/projects/.../memory/`, which only exists on Pat's machine.

---

## Prompt

You are the weekly maintenance agent for `pat-browne/nervepack`. You're running
in a fresh Anthropic cloud sandbox; the repo is cloned at your working
directory. You have NO access to anyone's local machine. Do these steps in
order, then stop.

### 1. Verify clone

```bash
ls CLAUDE.md skills setup agents .claude-plugin >/dev/null
```

If any are missing, stop and report.

### 2. Lint skills

For every `skills/<name>/SKILL.md`:

- Frontmatter present with `name:` (kebab-case, matches dirname) and
  `description:` (must say WHAT it teaches AND WHEN to use it).
- Description is specific enough that a future session can decide relevance
  from it alone — flag generics like "useful for coding".
- `[[link]]` references resolve to existing skills. Three or more dangling
  links to the same name → flag it (suggests a skill worth writing).
- No secrets, tokens, or private hostnames. Repo owner and commit identity are
  configured per-installation (`NP_GIT_AUTHOR_NAME` / `NP_GIT_AUTHOR_EMAIL`).

Fix small issues in-place. Note larger structural concerns in the commit
message — don't restructure unilaterally.

### 3. Audit cross-references

- Every dir under `skills/*/` has a corresponding entry in
  `.claude-plugin/plugin.json` `skills` array. Fix drift.
- README.md "Layout" section names every current skill. Fix drift.
- CLAUDE.md "Directory contract" table matches reality. Fix drift.

### 4. Commit + push

If anything changed:

```bash
# Author as the repo's configured git identity — never a bot name. `git config` without --global persists in
# .git/config and mis-authors later interactive commits (CLAUDE.md § Commit conventions).
# Commit identity: use the runner's existing git config; if unset (headless/cloud),
# fall back to NP_GIT_AUTHOR_* env, then a neutral bot. (Pat sets NP_GIT_AUTHOR_* in his
# cloud routine config to keep his attribution; a fork gets the fork-runner's identity.)
git config user.email >/dev/null 2>&1 || git config user.email "${NP_GIT_AUTHOR_EMAIL:-nervepack-agent@localhost}"
git config user.name  >/dev/null 2>&1 || git config user.name  "${NP_GIT_AUTHOR_NAME:-nervepack agent}"
# Stage AND commit ONLY the paths you changed — CLAUDE.md forbids `git add -A`/`.`/`-am`
# AND a pathspec-less `commit` (a bare commit re-commits the whole index, sweeping a
# concurrent session's staged work — issue #11). Path-limit BOTH; list what you touched:
_paths="skills sources wiki CLAUDE.md INDEX.md log.md"
git add $_paths
git commit -m "refine: weekly maintenance $(date -u +%F)" \
  -m "$(printf 'lint: %d skill issues\nxref: %d drifts' \
        "$LINT_FIXES" "$XREF_FIXES")" \
  -- $_paths
git push
```

If nothing changed, exit silently. No empty commits.

### 5. Report

One short paragraph:

- Lint fixes applied (count + brief list)
- Cross-reference drifts fixed (count)
- Upstream vendor sha (current vs recorded; "matches" if same)
- Any structural concerns flagged for the human

Scope ends here. No refactors, no new skills, no plugin reshuffling, no
README rewrites beyond fixing drift.
