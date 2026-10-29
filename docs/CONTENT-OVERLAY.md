# Content & team overlays

The engine (`~/Code/nervepack`) is shared machinery. Your skills, sources, memory, and
metrics live in a separate **content overlay** so they stay yours and sync on your own
repo. Configuring one is optional but recommended — skip it and the engine falls back to
its own root, which works but gives you nowhere personal to grow.

Part of the [getting-started](GETTING-STARTED.md) walkthrough.

## Personal overlay

Tell the engine where your content lives:

```bash
mkdir -p ~/.config/nervepack
echo "$HOME/Code/nervepack-content" > ~/.config/nervepack/content-dir
```

The `mkdir` is required the first time — `>` creates the *file* but not its parent
directory, so writing `content-dir` into a `~/.config/nervepack` that doesn't exist yet
fails with `no such file or directory`.

No overlay yet? Fork
[`nervepack-content-example`](https://github.com/pat-browne/nervepack-content-example),
rename it to something private, and point at that.

## Team overlay (optional)

You can point at a *second*, shared overlay that sits above your personal one:

```bash
echo "$HOME/Code/team-nervepack-content" > ~/.config/nervepack/team-dir
```

The stack becomes **team > personal > engine**. Reads merge with the team winning (a team
skill or playbook shadows your personal one of the same name), and writes still land in
your personal overlay unless you explicitly "save to the team layer." This is dormant
until a team dir resolves, and enabled by the `team` toggle.

For a nested organization, the value can be a **comma-separated list of up to four team
dirs**, highest-precedence first:

```bash
echo "$HOME/Code/squad-content,$HOME/Code/division-content,$HOME/Code/org-content" \
  > ~/.config/nervepack/team-dir
```

That stacks **squad > division > org > personal > engine** (the leftmost wins a name
clash). More than four team dirs is a hard error — the session falls back to
personal-only, and the doctor (`cli.py doctor`) flags the invalid config.

## Declaring your layout

nervepack does not assume your overlay uses any particular directory names. Each
layer says where its own content lives in a committed manifest,
`<layer>/.nervepack/layout.json`. The engine owns a small vocabulary of content
**kinds** (`skill`, `knowledge`, `reference`, `roadmap`, `prompt`); your layer maps
each kind to a path template.

```bash
NP="${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py"
python3 "$NP" layout show      --layer personal   # current routes + where they came from
python3 "$NP" layout questions --layer personal   # what the engine could not work out
```

A layer with **no** manifest still works: the engine infers routes from what is on
disk (a `skills/*/SKILL.md` tree, pages with frontmatter `kind:`, a root
`ROADMAP.md`, an `agents/` dir). Inference never guesses — where the shape is
unclear it reports an open question instead. Run the `np-core-layout` skill to
answer those and record the manifest, after which placement is deterministic.

Contribution refuses a kind your layer never routed, rather than inventing a
directory. `INDEX.md` and inbound links are what make a page findable, so directory
structure stays human convenience rather than a contract.

## Global host config (optional)

Two files under `config/` in your overlay carry the rules and settings every machine
should share. The engine seeds neither. Without them the sync does nothing.

| File | Holds | Lands in |
|---|---|---|
| `config/global-rules.md` | Host-neutral rules text | A managed block in each global instruction file |
| `config/host-settings.json` | Non-secret settings keys | `~/.claude/settings.json` |

**Rules.** The block sits between `nervepack:global-rules` markers. Targets are:

- Claude's `CLAUDE.md`, beside its settings file.
- Codex's `~/.codex/AGENTS.md`, when `~/.codex` exists.
- Any file listed in `adapter.json` under `global_config.instruction_files`.

Text outside the markers is never touched.

**Settings.** The overlay wins on the keys it lists. The base keys are
`enabledPlugins`, `extraKnownMarketplaces`, `theme` and `skipWorkflowUsageWarning`.
Add more names under a top-level `"allowlist"` array.

**Trust.** `theme` and `skipWorkflowUsageWarning` apply on their own. Marketplaces
and plugins load code, so they apply only on a machine that trusts them.

A marketplace applies when this machine already has it with the same source. It also
applies when its source or name is a line in `~/.config/nervepack/trusted-marketplaces`.
That file is per machine and never synced.

A plugin applies when its `@marketplace` passes the same rule. The sync skips the rest.
The doctor names each skipped item with the line to add, such as `github:owner/repo`.

Dicts merge, so local-only sub-keys survive. `hooks`, `permissions` and `env` are
never touched. A key whose name matches token, key, secret or password is refused at
any depth.

```json
{
  "theme": "dark",
  "enabledPlugins": {"example-plugin@example-marketplace": true},
  "allowlist": ["model"],
  "model": "example-model"
}
```

**Running it.** The sync runs at `cli.py setup install-hooks` and after each `sync`
that pulls. Run it by hand with `cli.py setup sync-global-config`. The `global-config`
doctor check reports drift.

**Turning it off.** `cli.py toggle global-config off` removes the blocks and the
settings keys the sync wrote. A key you changed since stays.

The fixture `engine/setup/tests/fixtures/example-layout/config/` shows the layout.

## Verify

```bash
python3 "${NP_DIR:-$HOME/Code/nervepack}/engine/setup/np-path-check.py" "${NP_DIR:-$HOME/Code/nervepack}" "${NP_CONTENT_DIR:-$HOME/Code/nervepack-content}"
```

Passing your overlay as a second argument checks that its skills and docs resolve too,
not just the engine's. A clean run prints `all setup/onboard path references resolve ✓`.
