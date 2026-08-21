# Graduation checklist — exact commands

Companion to `SKILL.md`. `$SKILL` = source skill dir in the personal overlay;
`$TEAM` = target team-overlay repo root; `ENG=~/Code/nervepack`.

## 1. Resolve the target layer

```bash
cat ~/.config/nervepack/team-dir 2>/dev/null; echo "NP_TEAM_DIR=${NP_TEAM_DIR:-unset}"
python3 $ENG/engine/nervepack_engine/np_content.py team_dir     # authoritative; "" = none
python3 $ENG/engine/nervepack_engine/np_content.py team_dirs    # list, highest-precedence first
python3 $ENG/engine/nervepack_engine/cli.py doctor              # flags invalid overlay config
```

- Empty → **STOP**. Report prerequisites to stand up a team overlay (a shared repo shaped
  like `nervepack-content`: `skills/`, `wiki/`, `INDEX.md`, own git remote; everyone sets
  `~/.config/nervepack/team-dir` or `NP_TEAM_DIR`; verify with
  `np-path-check.py $ENG $TEAM` + `doctor`). Do not fabricate a path.
- Comma-list → pick the tier by audience, confirm with the user.

## 2. Suitability / de-personalization gate

Read the whole skill and decide, with the user:

- **Don't graduate** — it is personal identity (one person's brand/aesthetic/paths).
- **De-personalized fork** — rewrite `name`/`description`/body team-neutral; keep only
  what the team shares. Grep for tells:

```bash
grep -rniE "pat|browne|~/Code/|pbrowne\.net|wiresandwizards" "$SKILL"
grep -oE '\[\[[^]]+\]\]' "$SKILL"/SKILL.md "$SKILL"/references/*.md | sort -u
```

## 3. Convention + structure checks

```bash
wc -c "$SKILL"/SKILL.md                                 # < 8192 hard, ~6144 soft
python3 $ENG/engine/setup/np_skill_budget.py            # split_candidates must be []
test "$(basename "$SKILL")" = "$(grep -m1 '^name:' "$SKILL"/SKILL.md | awk '{print $2}')" \
  && echo "dirname==name OK" || echo "MISMATCH"
```

Move the **whole directory** (incl. `references/`). Re-tier if the destination changes the
correct tier (an `np-env-*` that is really shared `np-kb-*`).

## 4. Pre-share safeguards (blocking)

```bash
# stage a copy, scrub it, then scan
STAGE=$(mktemp -d); cp -R "$SKILL/." "$STAGE/"
# ...apply de-personalization edits in $STAGE...
python3 $ENG/publish/np-publish-scan.py "$STAGE"        # exit 0 = clean; 1 = finding
grep -oE '\[\[[^]]+\]\]' "$STAGE"/SKILL.md "$STAGE"/references/*.md | sort -u   # resolve each
cat "$TEAM/INDEX.md" | grep -i "$(basename "$SKILL")"   # collision → update vs abort
```

Dangling links into personal-only skills → inline / drop / co-graduate. Never ship a team
skill that points into a private overlay.

## 5. Land it in the target overlay

Overlay skills need **NO `plugin.json` edit** (engine-only).

```bash
cd "$TEAM" && git fetch && git switch -c graduate-<name> origin/main
mkdir -p skills/<name> && cp -R "$STAGE/." skills/<name>/
python3 $ENG/engine/setup/np_link_skills.py            # team-aware relink
python3 $ENG/engine/setup/np_generate_index.py         # regenerate INDEX
git diff
git add skills/<name> INDEX.md                          # explicit paths, never -A
git commit -m "skill(<name>): graduate from personal overlay"
```

- **Team repo has review/CI** → `gh pr create --fill` filling its
  `PULL_REQUEST_TEMPLATE.md`; merge on green.
- **No CI** → announce to the team, then push. **Ask before pushing either way.** No LLM
  attribution.

## 6. Verify it wins

```bash
python3 $ENG/engine/setup/np_link_skills.py && python3 $ENG/engine/setup/np_generate_index.py
grep -i "<name>" "$TEAM/INDEX.md"                       # served from team layer
python3 $ENG/engine/nervepack_engine/np-path-check.py $ENG "$TEAM"
python3 $ENG/engine/nervepack_engine/cli.py doctor
```

Plus a fresh-agent application test: give a subagent only the graduated skill + a task;
confirm compliant output, no dangling refs, no reliance on a private overlay.

## 7. Retire the source (archive convention)

```bash
cd ${NP_CONTENT_DIR:-$HOME/Code/nervepack-content}
mkdir -p archive && git mv skills/<name> archive/<name>
# append a row to archive/MANIFEST.md:
#   | <name> | <YYYY-MM-DD> | graduated to team overlay | <team>:<name> |
python3 $ENG/engine/setup/np_link_skills.py && python3 $ENG/engine/setup/np_generate_index.py
git add archive/<name> archive/MANIFEST.md INDEX.md
git commit -m "skill(<name>): archive — graduated to team overlay"
# clear the graduation flag
rm -f ~/.cache/nervepack/graduation-candidates
```

**Never `rm`** the skill (history is immutable). **Keep-as-local-override** must use a
different name (`<name>-personal`) or the team copy shadows it.
