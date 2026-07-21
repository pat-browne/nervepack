# episodic-maintain

Local weekly task that drains the episodic capture inbox
(`~/.cache/nervepack/episodic-inbox/*.jsonl`) into themed `memory/episodic/<topic>.md`
files, compacts oversized ones, regenerates `memory/episodic/INDEX.md`, and
auto-commits + pushes. Runs as a user cron job — cloud agents can't see the
local inbox, so this has to stay local.

**Cadence:** Sunday 08:30 local — 30 min after `memory-promote` (08:00), same
spacing pattern the other nervepack agents use so no two push at once.

**Invoked by:** the `episodic-maintain` cron — `cli.py cron episodic-maintain`
(backed by `engine/setup/np_agentic_cron.py`, which invokes the agent via
`np-llm.sh`), logs to `~/.cache/nervepack/episodic-maintain.log`.

**Standing mandate:** pre-authorized to commit + push to the `memory/episodic/`
subtree only. This is the one subtree where the human-review gate is waived
(see `CLAUDE.md` → Episodic layer).

---

## Prompt

You are a scheduled local task running non-interactively via `claude -p` — no
human is watching. Do the work and exit. Don't ask questions. If something
blocks you, log it and stop.

Your job: drain the episodic capture inbox into nervepack's `memory/episodic/` layer.

### 1. Sync nervepack

```bash
~/Code/nervepack/engine/setup/40-sync-nervepack.sh --verbose
```

If the result is anything other than `up to date` or `fast-forwarded`, **stop**
— log "nervepack not in clean state — skipping episodic maintenance" and exit.

**Where the layers live (post content-cutover):** `memory/episodic/`,
`memory/lessons/` (and `wiki/`) live in the **content repo**, which is your **cwd**.

### 2. Read the inbox

```bash
INBOX="$HOME/.cache/nervepack/episodic-inbox"
ls "$INBOX"/*.jsonl 2>/dev/null
```

If there are no inbox files, exit silently — nothing to do, no empty commit.

Each line is one note: `{ts, project, cwd, mode, headline, body,
candidate_topics[], keywords[]}`.

### 3. Merge each note into a theme

For each note, in `ts` order:

- Pick the best topic. Prefer reusing an existing `memory/episodic/<topic>.md` or a
  `candidate_topics` slug that already maps to one. Check `memory/episodic/INDEX.md`
  and `wiki/` first so related work converges instead of fragmenting.
- If the topic file exists, prepend a new dated entry under the heading:
  `## [<date>] <project> — <headline>` followed by the `body`.
- If it doesn't exist, create it with the frontmatter in
  `memory/episodic/README.md` (`name`, `kind: episodic`, `last_updated`, `wiki`,
  `projects`). Add `[[wiki-entity]]` / `[[skill-name]]` cross-links in the
  `wiki:` list where the note clearly relates to an existing entity, concept,
  or skill — check `INDEX.md` and `wiki/` to find them. Dangling links are OK.
- Update `last_updated` and append the note's project to `projects` (dedupe).

### 4. Compact oversized themes

For any `memory/episodic/<topic>.md` over ~200 lines:

- Keep entries from roughly the last 8 weeks verbatim.
- Summarize older entries into (or fold into the existing) `## Rolled-up
  summary (through <date>)` block at the bottom — a few sentences capturing the
  durable gist. Delete the individual old entries you summarized.

If a theme has had no new entry in ~6 months and carries no inbound `[[links]]`,
retire it: `git mv memory/episodic/<topic>.md archive/episodic/<topic>.md`.

Also: if any entry reads like a durable rule/preference (not episodic state),
note it in your final report so a human can promote it via `np-core-contribute` —
do **not** write to `skills/` yourself; that path stays human-reviewed.

### 5. Regenerate `memory/episodic/INDEX.md`

Rewrite it from the current `memory/episodic/*.md` files, preserving the header from
`memory/episodic/README.md`'s format. One row per topic:

```
| <topic> | <last_updated> | <comma-separated keywords, deduped, ~8 max> | <line-count> |
```

Derive each row's keywords from the union of that theme's notes' `keywords`.

### 5b. Distill lessons from struggles and successes

After theming episodic notes, process the `struggles[]` and `strategies[]` arrays
across the inbox into ONE `memory/lessons/` layer. Each lesson carries a `provenance`
tag and, *independently*, an optional `enforce` block (provenance frames recall;
enforcement gates the tool call — the two are decoupled).

1. **Failures → `provenance: failure`.** Cluster recurring `struggles[]` by failure
   pattern. For each cluster, create or refresh `memory/lessons/<topic>.md` with
   `kind: lesson`, `provenance: failure`, and a **Symptom / Why / Do / Avoid** body
   synthesized from the struggle items.
2. **Successes → `provenance: success`.** Cluster recurring `strategies[]` by approach
   (reusable approaches that worked, ReasoningBank-shaped). For each cluster, create or
   refresh `memory/lessons/<topic>.md` with `kind: lesson`, `provenance: success`, and a
   **Title / When / Do** body from the `{title, description, content}` items. If a topic
   already holds a failure entry, add the success entry to the *same* file separated by a
   `---` line (one file per topic, entries stacked).
3. **`enforce` block (optional, any provenance).** Add one only when a pattern warrants
   gating at the tool call — almost always a failure with a detectable Bash signature:
   `tool_match` = an ERE matching the offending command (e.g. `sed -i .*s[#/]` or
   `git reset --hard`); `gate: ask` if any clustered item was `destructive`, else `warn`.
   **`tool_match` must not contain a literal `|`** (the INDEX column delimiter) — use
   character classes or separate lessons. If a `tool_match` would be dangerously broad
   (matches common safe commands), leave it empty and rely on `topic_triggers` injection.
   Entries with no `enforce` (or an empty `tool_match`) are advisory-only.
4. Set top-level `topic_triggers` from the items' topic_triggers (drives
   `engine/nervepack_engine/hooks/lesson_recall.py` injection; for enforced entries it
   also drives `engine/nervepack_engine/hooks/lesson_guard.py`). Increment `seen` when a
   cluster matches an existing lesson.
5. Regenerate `memory/lessons/INDEX.md` — a Markdown table whose data rows are
   `| <topic> | <tool_match> | <gate> | <topic_triggers> |` (empty `tool_match`/`gate`
   cells for advisory entries), so `engine/nervepack_engine/hooks/lesson_guard.py`'s
   parser reads it unchanged.
6. In your final report, FLAG lessons with high `seen` (≥3) as **promotion candidates**
   for a human to graduate into a `skills/np-kb-*` rule via `np-core-contribute`. Prune
   stale/disproven lessons to `archive/lessons/`.

### 6. Commit, push, clear inbox

If `memory/episodic/` changed — commit + push **the cwd repo** (the content repo; do NOT
`cd` away):

```bash
# cwd is the content repo (np_content_dir) — stay here.
# Author as the repo's configured git identity — never a bot name. `git config` without --global persists in
# .git/config and mis-authors later interactive commits (CLAUDE.md § Commit conventions).
# Commit identity: use the runner's existing git config; if unset (headless/cloud),
# fall back to NP_GIT_AUTHOR_* env, then a neutral bot. (Pat sets NP_GIT_AUTHOR_* in his
# cloud routine config to keep his attribution; a fork gets the fork-runner's identity.)
git config user.email >/dev/null 2>&1 || git config user.email "${NP_GIT_AUTHOR_EMAIL:-nervepack-agent@localhost}"
git config user.name  >/dev/null 2>&1 || git config user.name  "${NP_GIT_AUTHOR_NAME:-nervepack agent}"
# Path-limit BOTH `add` and `commit` — a bare commit re-commits the whole index and
# sweeps a concurrent session's staged work into this drain (issue #11).
_paths="memory/episodic archive/episodic memory/lessons archive/lessons"
git add $_paths
git commit -m "episodic(maintain): weekly drain ($(date -u +%F))" \
  -m "Themes touched: <list>. Notes merged: <N>. Compacted: <list or none>." \
  -- $_paths
git push
```

Only after a successful commit, clear the processed inbox files:

```bash
rm -f "$HOME/.cache/nervepack/episodic-inbox"/*.jsonl
```

If `memory/episodic/` did not change, do not commit and do not clear the inbox.

### 7. Report

Print one short summary (it lands in the log): notes merged, themes touched,
themes compacted/retired, and any entries that looked durable and should be
promoted to a skill by a human.

Scope ends here. Don't touch `skills/`, `sources/`, or `wiki/` content beyond
reading them to pick topics and cross-links.
