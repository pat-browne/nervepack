---
id: 0018
status: proposed
date: 2026-08-22
tier: high
blast_radius:
  - engine/setup/np_host.py
  - engine/setup/np_link_skills.py
  - engine/setup/np_toggle_audit.py
  - engine/setup/risk-tiers.json
  - engine/nervepack_engine/**
  - engine/onboard/adapters/**
  - engine/setup/tests/**
  - .github/CODEOWNERS
  - docs/HOST-ADAPTERS.md
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0018: an adapter should say where the host keeps things (F11, #300)

## Context and problem statement

#257 asked for Claude-Code-specific wiring to move behind a host-adapter
directory. Measuring first showed most of that already exists:
`engine/onboard/capabilities.json` is a tool-neutral contract of eighteen
capabilities with per-host hints for claude-code, goose, cursor, codex and a
generic fallback; `engine/onboard/adapters/*.example.json` are reference
manifests; `~/.config/nervepack/adapter.json` carries a `verify` command per
capability; and `np_doctor` already runs adapter-driven checks.

The gap is narrower than the issue implied. **An adapter says how to VERIFY a
capability. It does not say WHERE the host keeps anything.** So the code that
does the wiring names the host directly, and the same decision is written out
more than once:

```
CLAUDE_SETTINGS or ~/.claude/settings.json   np_doctor x2, np_toggle,
                                             np_toggle_audit, np_hook   -> 5 copies
NP_SKILLS_DST   or ~/.claude/skills          np_link_skills             -> 1
CLAUDE_PROJECTS_DIR or ~/.claude/projects    backcapture_sweep,
                                             resume_sessionstart,
                                             resume_write               -> 3
```

Five copies of one resolution is the same shape `np_dirs` fixed for state
directories, and it has the same consequence: a host whose settings file lives
elsewhere has to be taught in five places, and a sixth copy is one commit away.

## Decision

We will add `np_host.py` with `settings_path()`, `skills_dir()` and
`transcripts_dir()`, and route all nine call sites through it.

Each resolves in the same order, and the order is the point:

1. **The existing environment variable** — `CLAUDE_SETTINGS`, `NP_SKILLS_DST`,
   `CLAUDE_PROJECTS_DIR`. These are documented escape hatches, `capabilities.json`
   already tells a non-Claude host to use one, and nothing about them changes.
2. **A `paths` block in `adapter.json`**, which is new.
3. **Today's `~/.claude/...` default.**

The environment keeps winning because it already did. An adapter manifest is a
per-machine file written once at onboarding; an environment variable is what
someone reaches for when the manifest is wrong, and a manifest that could not be
overridden would be worse than no manifest.

## What the adapter gains

```json
{
  "host": "claude-code",
  "paths": {
    "settings":    "~/.claude/settings.json",
    "skills_dir":  "~/.claude/skills",
    "transcripts": "~/.claude/projects"
  },
  "capabilities": { ... }
}
```

Optional in full and in part: an adapter with no `paths`, or with only one of
the three, behaves exactly as today for whatever it omits. That matters because
the manifests already on disk have no `paths` block, and this change must not
require anyone to rewrite one.

`~` is expanded, because a hand-written manifest will contain it.

## Non-goals

- **The hooks keep speaking the host's protocol.** `engine/nervepack_engine/hooks/**`
  parse Claude Code's payload shapes and emit its `permissionDecision` fields.
  That is what an adapter IS. The point of a port is that the tool-neutral core
  does not know the host's name, not that no file does.
- **No new host.** This makes a second host expressible; it does not add one.
- **`np_dirs` is untouched.** Nervepack's own state, not the host's.

## Cross-cutting concerns

**Security.** `settings_path()` resolves a file this repo WRITES to — the hook
registrar rewrites it. A wrong answer either edits the wrong file or silently
registers hooks nowhere. The resolver never creates anything and never follows a
relative value from a manifest, for the same reason `np_dirs` does not: these
resolve inside hooks that start in an arbitrary directory.

**Privacy.** A manifest may name a path under the user's home. It already did.

**Observability.** `np_doctor` reports the resolved settings path when it is not
the default, matching what #301 did for state directories.

**Portability.** A manifest is per-machine and uncommitted, so a Windows adapter
can name a Windows path without a platform branch in code.

## Consequences

**Good.** A host whose settings live elsewhere is now a manifest edit rather than
a code change in five files. The five copies of the settings resolution become
one.

**Bad.** Resolution gains a layer, so "why did it pick that path" now has three
possible answers instead of two. The doctor reporting a non-default path is the
mitigation.

**Neutral.** Nothing moves. With no `paths` block — which is every machine today
— all three resolve exactly where they did.

## Confirmation

- `test_np_host.py` asserts the precedence order, that a missing or partial
  `paths` block falls back per-key, that `~` is expanded, that a relative value
  is rejected, and that the resolver creates nothing.
- A test asserts no tool-neutral module names `.claude` in code any more, with
  `engine/nervepack_engine/hooks/**` and `np_hook.py` explicitly exempt as the
  adapter layer.
- The three `adapters/*.example.json` files gain a `paths` block and still parse.

## Rollback

`git revert`. `np_host` reads a key that does not exist on any machine today, so
with no `paths` block present the reverted code resolves identically — the same
property that makes `np_dirs` revertible.

A machine that has since added a `paths` block would go back to `~/.claude/...`
after a revert. Set the matching environment variable (`CLAUDE_SETTINGS`,
`NP_SKILLS_DST`, `CLAUDE_PROJECTS_DIR`) to restore the manifest's answer, since
those take precedence in both versions.
