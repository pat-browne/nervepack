# Host adapters

Nervepack's engine is tool-neutral. Everything that knows about a specific
agentic host lives behind an adapter.

## What was already here

| Piece | Where |
|---|---|
| Capability contract, 18 capabilities with per-host hints | `engine/onboard/capabilities.json` |
| Reference manifests | `engine/onboard/adapters/*.example.json` |
| The machine's own manifest | `~/.config/nervepack/adapter.json` |
| Adapter-driven health checks | `np_doctor`, running each capability's `verify` |

Hints already cover claude-code, claude-code-macos, claude-code-windows, goose,
cursor, codex and a `generic` fallback. This is a real port, not a stub.

## What #300 added

An adapter said how to **verify** a capability. It did not say **where** the host
keeps anything, so the code doing the wiring named the host directly — and the
same decision was written out five separate times for the settings file alone.

Adapters now carry an optional `paths` block:

```json
{
  "host": "claude-code",
  "paths": {
    "settings":    "~/.claude/settings.json",
    "skills_dir":  "~/.claude/skills",
    "transcripts": "~/.claude/projects"
  }
}
```

`engine/setup/np_host.py` resolves all three, and every call site goes through
it.

## Resolution order

1. **The environment variable** — `CLAUDE_SETTINGS`, `NP_SKILLS_DST`,
   `CLAUDE_PROJECTS_DIR`
2. **The adapter's `paths` entry**
3. **The built-in `~/.claude/...` default**

The environment wins because it always did. `capabilities.json` already tells a
non-Claude host to set `CLAUDE_SETTINGS`, and a manifest is written once at
onboarding — so the variable is what someone reaches for when the manifest is
wrong. A manifest that could not be overridden would be worse than no manifest.

## Optional in full, and per key

Omit the block, or any single key, and the default applies to whatever is
missing. Every manifest written before this change has no `paths` block and
keeps working unchanged.

`~` is expanded, because a manifest is hand-written. A **relative** value is
ignored and reported by the doctor — the same rule as `np_dirs`, for the same
reason: these resolve inside hooks that start in whatever directory the user
opened.

A malformed or missing manifest resolves to the defaults rather than failing.
`np_hook` and the recall hooks resolve through here, and hooks fail open, so a
bad manifest key must not be able to take the session lifecycle down with it.

## What is still allowed to know the host's name

Three places, and a test asserts the list does not grow:

```
engine/nervepack_engine/hooks/     parse the host's payloads, emit its verdicts
engine/nervepack_engine/np_hook.py registers hooks in the host's settings file
engine/setup/np_host.py            the resolver itself
```

**That is what an adapter is.** The point of a port is that the tool-neutral core
does not know the host's name, not that no file does.

One thing deliberately not flagged: `np_layout` lists `.claude` in a frozenset of
directory names it will not walk into, beside `.git` and `node_modules`. That is
membership, not resolution, and treating it as a violation would push a correct
skip-list into an exemption list.

## Adding a host

1. Copy the nearest `engine/onboard/adapters/*.example.json` to
   `~/.config/nervepack/adapter.json`.
2. Set `host`, and `paths` if the host does not keep things under `~/.claude`.
3. Fill each capability's `verify` with a command that exits 0 when that
   capability is genuinely wired. `capabilities.json` carries a hint per host.
4. Run `cli.py doctor`. Adapter-driven capabilities run your `verify` commands.

Related: `docs/XDG-DIRECTORIES.md` (nervepack's own state, a different question),
`change-specs/feat-f11-host.md`, issue #300.
