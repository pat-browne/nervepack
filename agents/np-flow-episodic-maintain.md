# episodic-maintain

Local weekly task that drains the episodic capture inbox
(`~/.cache/nervepack/episodic-inbox/*.jsonl`) into themed `memory/episodic/<topic>.md`
files, compacts oversized ones, regenerates `memory/episodic/INDEX.md`, and
auto-commits + pushes. Runs as a user cron job — cloud agents can't see the
local inbox, so this has to stay local.

**Cadence:** Sunday 08:30 local — 30 min after `memory-promote` (08:00), same
spacing pattern the other nervepack agents use so no two push at once.

**Invoked by:** the `episodic-maintain` cron — `cli.py cron episodic-maintain`
(backed by `engine/setup/np_agentic_cron.py`, which invokes the agent via the
model seam `np_model.py`), logs to `~/.cache/nervepack/episodic-maintain.log`.

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
python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py" sync --verbose
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

If there are no inbox files, skip steps 3-5b. Still run step 6 when
`git status --porcelain memory/resources` is non-empty: the cron has already merged
the resources inbox into `memory/resources/` (deterministic, no action from you).
With neither, exit silently — no empty commit.

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

1. **Body format: paired rules under objective headings.** Every lesson body is
   `## <objective>` headings (the goal a session is pursuing, e.g. "Search a repo
   reliably"), each followed by one line per rule:

   ```
   ## <objective>
   - DON'T <x> → DO <y> — **when** <scope> — **why** <reason>. [[episodic/<topic>]]
   ```

   Rules: DON'T → DO is the default (always pair the avoid with its alternative). A
   **lone DO** is allowed for a win with no real anti-pattern — **never invent a
   DON'T**; a lone DON'T is a lint finding. **when** (where the rule applies) and
   **why** (the reason, so a session can handle an unanticipated case) are both
   required, labelled, and separate. Budget: ≤ 2 lines / ~320 chars per entry. The
   scenario narrative (the old Symptom) does NOT go in the lesson — it stays in
   `memory/episodic/<topic>.md`, reached by the trailing `[[episodic/<topic>]]` backlink.
2. **Failures → `provenance: failure`.** Cluster recurring `struggles[]` by failure
   pattern. For each cluster, create or refresh `memory/lessons/<topic>.md` with
   `kind: lesson`, `provenance: failure`, and paired-rule entries (DON'T → DO)
   synthesized from the struggle items.
   **Successes → `provenance: success`.** Cluster recurring `strategies[]` by approach
   (reusable approaches that worked, ReasoningBank-shaped). Create or refresh
   `memory/lessons/<topic>.md` with `kind: lesson`, `provenance: success`, and
   paired-rule entries from the `{title, description, content}` items (lone DO when
   there is no genuine anti-pattern). If a topic already holds a failure entry, add the
   success entry to the *same* file as a second, **complete** frontmatter block (its own
   `---` … `---` with `name`, `kind`, `provenance`, `topic_triggers`, …) followed by its
   body (one file per topic, entries stacked). Never separate entries with a bare `---`:
   recall and the linter read every `---` as a frontmatter delimiter, so a bare one
   turns the next entry's body into frontmatter and that entry is never recalled.
   Legacy-format files (Symptom/Why/Do/Avoid or Title/When/Do bodies) are converted by
   `np-migrate-lessons.py --bodies <content_root>`, not hand-rewritten; the linter flags
   them as `legacy-format`.
3. **`enforce` block (optional, any provenance).** Add one only when a pattern warrants
   gating at the tool call — almost always a failure with a detectable Bash signature:
   `tool_match` = an ERE matching the offending command (e.g. `sed -i .*s[#/]` or
   `git reset --hard`); `gate: ask` if any clustered item was `destructive`, else `warn`.
   **`tool_match` must not contain a literal `|`** (the INDEX column delimiter) — use
   character classes or separate lessons. If a `tool_match` would be dangerously broad
   (matches common safe commands), leave it empty and rely on `topic_triggers` injection.
   Entries with no `enforce` (or an empty `tool_match`) are advisory-only.
   For a non-Bash tool call (Phase 2), set `enforce.tool_name_match` instead — matched
   as a regex via `re.fullmatch`, so an exact tool name (`"Edit"`, `"Read"`) still
   matches exactly, but an alternation can target a whole family of MCP tool names in
   one lesson (e.g. `"^(Edit|Write|mcp__.*__(repo_create_pull_request|repo_reply_to_comment))$"`)
   — needed because an MCP tool name embeds a server id that varies by plugin/version.
   Phase 2 only fires for a tool name that `hooks.manifest` actually registers a
   `PreToolUse` matcher for (currently `Bash`/`Read`/`Edit`/`Write`/`Skill`/`mcp__.*`);
   a lesson targeting a tool outside that set needs a new manifest row too.
4. Set top-level `topic_triggers` from the items' topic_triggers (drives
   `engine/nervepack_engine/hooks/lesson_recall.py` injection; for enforced entries it
   also drives `engine/nervepack_engine/hooks/lesson_guard.py`). Increment `seen` when a
   cluster matches an existing lesson.
5. Regenerate `memory/lessons/INDEX.md` — a Markdown table whose data rows are
   `| <topic> | <tool_match> | <gate> | <topic_triggers> |` (empty `tool_match`/`gate`
   cells for advisory entries), so `engine/nervepack_engine/hooks/lesson_guard.py`'s
   parser reads it unchanged.
6. **Discoverability backlink.** For each lesson file written, if a matching overlay
   skill (`skills/<name>/SKILL.md`) or wiki topic page (`wiki/topics/<topic>/<topic>.md`)
   clearly matches the topic, add a `Lessons: [[lessons/<topic>]]` line to it unless
   already present (so hosts without the recall hook still find lessons). That line is
   the ONLY edit allowed to those pages. No clear match → skip.
7. **Lint gate (before committing).** Run the linter over the changed lesson files:
   `python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/setup/np_lesson_format.py" lint memory/lessons/*.md`
   (limit to files you changed). On any finding (`missing-when`, `missing-why`,
   `lone-dont`, `too-long`, `legacy-format`), fix and re-lint. If it still fails, revert
   the lessons write (`git checkout -- memory/lessons`, and remove new untracked lesson
   files) and list the findings in the final report.
8. In your final report, FLAG lessons with high `seen` (≥3) as **promotion candidates**
   for a human to graduate into a `skills/np-kb-*` rule via `np-core-contribute`. Prune
   stale/disproven lessons to `archive/lessons/`.

### 6. Commit, push, clear inbox

If `memory/episodic/` or `memory/resources/` changed — commit + push **the cwd repo** (the content repo; do NOT
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
_paths="memory/episodic archive/episodic memory/lessons archive/lessons memory/resources"
# Only if step 5b ran: also add each skill/wiki page that got a `Lessons: [[lessons/<topic>]]`
# backlink, explicitly (e.g. _paths="$_paths skills/<name>/SKILL.md"). Never -A.
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
