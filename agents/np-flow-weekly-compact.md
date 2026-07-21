# weekly-compact

Recurring agent prompt for *dreaming* — the consolidation pass that keeps this
nervepack repo from accumulating duplicate or bloated skills. Installed as a
weekly local cron (Wednesday) via `cli.py setup install-memory-cron` — default-on,
toggle `maintain.compact` to disable. May also be run as an optional cloud
routine or OSS runner; see `agents/README.md` for the optional offload setup.

**Cadence:** weekly (Wednesday). As a local cron: `0 10 * * 3` (10:00 local),
mid-week between `nervepack-refine` runs (Sunday) — avoids both routines racing
each other to push. When deployed as a cloud routine, use `0 15 * * 3`
(Wed 15:00 UTC) or your preferred equivalent.

**Where this runs:** wherever this is scheduled — a local cron, a cloud routine,
or an OSS runner. The repo is at your working directory. No local-machine access.

**Standing mandate:** pre-authorized to auto-merge skills with very high
similarity (Jaccard ≥ 0.85 on description + section headings) AND to
auto-archive duplicates. For everything else, write proposals to a dated
file under `compact-proposals/` and let the human decide.

---

## Prompt

You are the weekly *compaction* agent for this nervepack repo. You run wherever
this is scheduled — a local cron, a cloud routine, or an OSS runner. The repo is
at your working directory. You have NO access to anyone's local machine. Do these
steps in order, then stop.

### 1. Verify repo

```bash
ls CLAUDE.md skills setup INDEX.md >/dev/null
```

If any are missing, stop and report.

### 2. Build a similarity matrix across skills

For every pair of skills in `skills/*/SKILL.md`:

- Extract the frontmatter `description:` (one sentence).
- Extract all `##`-level section headings.
- Tokenize: lowercase, strip punctuation, drop stopwords (use a small
  built-in list: the, a, an, and, or, of, to, for, in, on, with, when,
  use, that, this, is, are, be).
- Compute Jaccard similarity = |A ∩ B| / |A ∪ B| over the union of tokens
  from description + headings.

Record pairs above 0.3 similarity, ranked descending.

### 3. Auto-merge confident duplicates (Jaccard ≥ 0.85)

For each pair above 0.85:

1. Pick the keeper: the skill with more lines (more accumulated content),
   tie-break by alphabetical name.
2. Merge the *unique* sections from the loser into the keeper, preserving
   the keeper's structure. Do not duplicate identical content; just append
   what's new.
3. Update the keeper's frontmatter `description:` to cover both old
   descriptions — a single sentence that subsumes both intents.
4. Move the loser to `archive/<loser-name>/` and append a row to
   `archive/MANIFEST.md`:
   ```
   | <loser-name> | $(date -u +%F) | merged into <keeper-name> (Jaccard X.XX) | <keeper-name> |
   ```
5. Remove the loser's entry from `.claude-plugin/plugin.json`.

### 4. Propose ambiguous merges (0.4 ≤ Jaccard < 0.85)

Write a proposal file at `compact-proposals/$(date -u +%F).md` if any
pairs in this band exist. For each pair, include:

- Both names, both descriptions, both line counts, the Jaccard score
- A diff of what the merged skill would look like (use the same logic as
  step 3, but as a dry-run printed inline)
- A short recommendation: "merge", "merge with rewrite", or "keep separate
  — they overlap but serve different triggers"

Don't apply these — they're for human review next session.

### 5. Propose splits for oversized skills

For any `SKILL.md` over 300 lines:

- Identify the section boundaries (`##`-level headings).
- If two or more sections could stand alone as their own skill, propose a
  split in `compact-proposals/$(date -u +%F).md` (append, don't overwrite
  step 4's output).
- Don't apply splits — splits are taste-heavy, always human.

### 6. Regenerate INDEX.md

```bash
./setup/60-generate-index.sh
```

### 7. Commit + push

Make two separate commits if both happened:

**Commit A — auto-applied merges/archives** (only if step 3 did anything):
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
git add skills archive INDEX.md .claude-plugin/plugin.json
git commit -m "compact: auto-merge $N skill(s)" -m "$(cat <<EOF
Merged via Jaccard ≥ 0.85 on description + headings:
- <loser> → <keeper> (score X.XX)
- ...

INDEX.md regenerated. Archive manifest updated.
EOF
)" -- skills archive INDEX.md .claude-plugin/plugin.json   # same explicit paths
```

**Commit B — proposals** (only if step 4 or 5 wrote anything):
```bash
git add compact-proposals/
git commit -m "compact: $M proposal(s) for review" -- compact-proposals/
```

Then `git push`.

If nothing changed, exit silently. No empty commits.

### 8. Report

One short paragraph:

- N auto-merges applied (with from→to names + scores)
- M proposals written to `compact-proposals/<date>.md`
- K splits proposed
- Any structural concerns (e.g. "5 skills all in the 0.3-0.4 band — maybe
  consider a topic reorganization")

Scope ends here. Don't lint frontmatter (that's the refine agent's job).
Don't update CLAUDE.md or README. Don't touch `vendor/`.
