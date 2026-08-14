# Steps

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
   python3 ~/Code/nervepack/engine/nervepack_engine/cli.py layout route \
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
6. **Relink + regenerate INDEX:** `python3 ~/Code/nervepack/engine/nervepack_engine/cli.py setup link-skills`
   (handles new skills in every layer, prunes dangling symlinks, and re-runs
   `cli.py setup generate-index`).
7. **Diff:** `git -C "$REPO" diff` — show the user.
8. **Commit** with conventional subject (see `AGENTS.md` § "Commit conventions",
   also gated by [[np-flow-concise-output]]),
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
