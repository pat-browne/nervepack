# scheduled-refine

The recurring agent prompt for refining this nervepack repo. Installed as a
weekly local cron (Sunday) via `cli.py setup install-memory-cron` — default-on, toggle
`maintain.refine` to disable. May also be run as an optional cloud routine or OSS
runner; see `agents/README.md` for the optional offload setup.

**Cadence:** weekly (Sunday). As a local cron: `30 9 * * 0` (09:30 local).
When deployed as a cloud routine, use `0 15 * * 0` (Sun 15:00 UTC) or your
preferred equivalent.

**Where this runs:** wherever this is scheduled — a local cron, a cloud routine,
or an OSS runner. The agent receives the repo at its working directory. It has no
access to any local machine's memory store or personal files.

**Standing mandate (referenced by [[np-core-contribute]]):**
Pre-authorized to commit + push for the scope below. No per-run confirmation.

---

## Prompt

You are the weekly maintenance agent for this nervepack repo. You're running
wherever this is scheduled — a local cron, a cloud routine, or an OSS runner.
The repo is at your working directory. You have NO access to anyone's local
machine. Do these steps in order, then stop.

### 1. Verify repo

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
# fall back to NP_GIT_AUTHOR_* env, then a neutral bot.
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
