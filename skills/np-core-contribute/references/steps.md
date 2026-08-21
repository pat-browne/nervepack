# Steps

0. **Preflight for other writers.** `git -C "$REPO" fetch --quiet && git -C "$REPO"
   status --short`. Both repos are one working tree shared with other sessions and
   with crons that commit to `skills/` (`memory-promote` 08:00, `skill-maintain`
   09:15). Clean tree, or dirty only outside your target paths → work in place.
   Dirty **in a path you intend to edit**, or you are a background session, or the
   edit spans several files → isolate in a worktree first. Decision table, the
   `EnterWorktree` contract, and the per-repo relink hazards:
   references/isolation.md
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
3. **Resolve the target path.** Classify the learning as one kind from the table,
   then ask the layer where that kind lives:
   ```bash
   python3 ${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py layout route \
     --layer personal --kind knowledge --variant concept --value name=<name>
   ```
   It prints one path relative to the layer root. When it reports that the kind
   needs a variant, the message lists each variant with the layer's own rule for
   choosing. When it reports no route for the kind, invoke [[np-core-layout]] to
   add one, then retry. Never invent a directory, and never hardcode one here.
   (Or reuse the existing skill identified in step 2.)
4. **Write the update.** For an existing skill: minimal surgical edit. For
   a new skill: include `---` frontmatter with `name:` and `description:`.
   The description must say WHAT it teaches and WHEN to use it — specific
   enough that step 2 will work for the next contributor. Before moving on,
   run the draft through [[np-flow-concise-output]] — SKILL.md bodies and
   wiki/sources pages are explicitly in its scope, and it catches the padding
   this protocol otherwise ships straight into a durable file.
4b. **Guarantee an inbound link.** A page nothing links to is a page nobody finds.
   Add a `[[wikilink]]` from a related page or the index (use a relative path when
   the layout's `links` is `path` — `cli.py layout show` reports it). Directory
   position is human convenience; the link and `INDEX.md` are the real contract.
5. **New engine skill only:** append `./skills/<name>` to the `skills` array
   in the engine's `.claude-plugin/plugin.json`. Overlay skills are picked up
   by the relink alone.
6. **Relink + regenerate INDEX:** `python3 ${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py setup link-skills`
   (handles new skills in every layer, prunes dangling symlinks, and re-runs
   `cli.py setup generate-index`). Run it **after your final edit** — it records each
   skill's line count, so regenerating mid-edit ships an `INDEX.md` row that disagrees
   with the file (observed: a trim to get under budget landed after the regen, and the
   commit carried a stale count). Run it in the **primary checkout, never an engine
   worktree** — it would repoint every host skill symlink into the worktree.
   It regenerates `INDEX.md` from *every* skill in the tree, so if another writer has
   uncommitted edits, check `git -C "$REPO" diff -- INDEX.md` and expect only your own
   rows to move. If it carries someone else's, leave `INDEX.md` unstaged and say so.
   **Use that exact verb.** `cli.py` lives at `engine/nervepack_engine/cli.py`, not the
   repo root, and an unrecognised or bare invocation **exits 0 printing nothing** — so a
   guessed verb (`cli.py index`, `cli.py relink`) looks like a successful no-op. Confirm
   by the effect, not the exit code: `INDEX.md` must appear in `git status`.
7. **Diff:** `git -C "$REPO" diff` — show the user. Deliver it as a rendered diff,
   not a description ([[np-flow-deliver-diff]]).
8. **Commit** with conventional subject (see `AGENTS.md` § "Commit conventions",
   also gated by [[np-flow-concise-output]]). Stage explicit paths **and pass the same
   pathspec to `commit`** — a bare `commit` after an explicit `add` still commits the
   whole index, so it captures whatever another session staged:
   ```bash
   git -C "$REPO" add <changed paths>
   git -C "$REPO" commit -m "skill(<name>): <what changed>" -- <changed paths>
   ```
   No LLM attribution trailer — see `AGENTS.md` § "Commit conventions".
9. **Ask before pushing.** Push is the action that affects another machine.
   Default to `git -C "$REPO" push` only after the user confirms — unless
   they've said "auto-push" or this run was invoked from a scheduled agent
   (which has a standing mandate; see `agents/np-flow-scheduled-refine.md` and
   `agents/np-flow-weekly-compact.md`). **Engine changes never direct-push** —
   `np-core-*`/`np-flow-*` skills and anything under `engine/` or `dashboard/` go
   through a PR that merges on green CI, with a company-neutral message. The private
   overlay has no CI gate and may be pushed directly.
