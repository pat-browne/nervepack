---
id: 0021
status: proposed
date: 2026-08-28
tier: high
blast_radius:
  - engine/nervepack_engine/np_toggle.py
  - engine/nervepack_engine/np_content.py
  - engine/nervepack_engine/cli.py
  - engine/nervepack_engine/hooks/turn_gate.py
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/nervepack_engine/hooks/form_directive.py
  - engine/setup/hooks.manifest
  - engine/setup/toggles.conf
  - engine/setup/tests/nervepack_engine/**
  - engine/setup/tests/toggles/**
  - engine/setup/tests/content/**
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0021: make the output contract enforceable, and make the preference portable

## Context and problem statement

`np-flow-concise-output` states the output contract. Two hooks exist to enforce
it, `form_gate` on PreToolUse and `turn_gate` on Stop. Neither one holds today,
for four separate reasons.

1. **Chat output is never gated before a reader sees it.** `turn_gate` runs on
   Stop, after the closing message already streamed to the terminal. Its form
   check is set to `warn`, which appends context that only a later turn reads.
2. **File writes are not gated either.** `form_gate.categorical` ships `warn`,
   which returns `allow` plus a note. The write lands. The documented reason
   for shipping `warn` is a corpus scan that found 579 pre-existing categorical
   violations across the content overlay.
3. **Coverage is narrow.** `form_gate` reads four file extensions and four MCP
   tool suffixes. Work-item comments, PR thread replies, wiki page upserts,
   Notion page creation, Slack canvases, and mail drafts all pass untouched,
   although the skill names review-thread replies as the highest-volume text a
   reviewer reads.
4. **Subagents are not gated at all.** No `SubagentStop` row exists in
   `hooks.manifest`, so every agent in a fan-out writes and reports with no
   form check.

A fifth problem sits underneath all four. The preference must hold on every one
of the maintainer's machines, and it must not be hardcoded in the engine, which
other people fork. The toggle resolver offers only two layers today:
`~/.config/nervepack/toggles.local`, which is untracked and therefore
per-machine, and `engine/setup/toggles.conf`, which is committed to the engine
and therefore shared with every forker. Neither layer is both portable and
personal. The `form_gate.exempt_globs` value already demonstrates the gap: it
lives in `toggles.local` on one machine and nowhere else.

## Considered options

1. **Set the aggressive values in `engine/setup/toggles.conf`.** Good, because
   it needs no new code and syncs with the engine. Bad, because it imposes one
   maintainer's calibration on every forker, and the engine is meant to ship
   safe defaults. Rejected.
2. **Copy `toggles.local` between machines by hand or by a sync script.** Good,
   because the resolver needs no change. Bad, because an untracked file has no
   history, no conflict resolution, and no record of why a value changed.
   Rejected.
3. **Add a content-overlay toggle layer between local and engine.** Good,
   because the content overlay is already a git repo that already syncs across
   machines, and the layer is already the established seam for anything
   personal. Neutral, because it adds a third precedence step to a resolver
   that four call sites read. Chosen.
4. **Gate chat output before it streams.** Rejected as impossible. The harness
   streams assistant text as it is produced. No hook event fires between
   production and display.

## Decision

We will make four changes, each toggle-controlled, with engine defaults left at
their current permissive values.

**A. A content-overlay toggle layer.** `np_toggle` will resolve a feature state
or param through three files in order: `~/.config/nervepack/toggles.local`,
then `<content_dir>/config/toggles.conf`, then `engine/setup/toggles.conf`. The
new middle file uses the identical pipe-delimited format, so one parser serves
all of them. `NP_TOGGLES_CONTENT` overrides its path for tests. A machine with
no content overlay resolves exactly as it does today.

**B. Prevention first, blocking as a backstop.** A new `form_directive`
UserPromptSubmit hook injects a compact form contract into every turn, so the
first draft is clean and the gate rarely fires. `turn_gate.form` gains a `block`
mode. When it blocks, the reason forbids restating the message and asks for a
short replacement, because a Stop-hook block appends to text the reader already
saw. Zero duplicate output cannot be promised at Stop. Prevention is what makes
it rare, and this is recorded as an accepted limit rather than a solved problem.

**C. `form_gate.categorical` becomes settable to `ask`, and Write lints the
delta.** `Write` on an existing file will lint only the text the write adds,
the way `Edit` already lints only `new_string`. Legacy prose then stops firing
the gate, which removes the stated blocker on `ask`.

**D. Coverage widens.** The prose extension list becomes the toggle param
`form_gate.prose_ext`. Eight more MCP tool suffixes are extracted. A
`SubagentStop` row registers `turn_gate` for subagents, under its own
`turn_gate.subagent` param.

## Non-goals

- Gating source files. Comments and docstrings inside code stay out of scope,
  because the linter strips code and would score the remainder unreliably.
- Rewriting the 579 pre-existing violations. Delta linting makes them moot.
- Promoting the rate-based rules from advisory to blocking. Passive-voice
  detection stays a heuristic, and a heuristic must not block.
- Changing engine defaults. Every aggressive value lands in the maintainer's
  content overlay, not in this repo.

## Cross-cutting concerns

- **Security:** the new toggle layer reads a file path from
  `np_content.content_dir()`, which is already trusted by every recall hook. No
  new input is trusted. The parser is the existing one and executes nothing.
- **Privacy:** the content overlay holds personal paths today, which is why
  `exempt_globs` moves there rather than into this repo. The engine PII guard
  keeps rejecting a personal path committed here.
- **Observability:** each gate keeps writing a `np_toggle.signal` line, and the
  new directive hook is silent by design. `np-core-doctor` gains no new check in
  this change.

## Consequences

- Good, because the preference becomes one tracked file that reaches every
  machine through a sync that already runs.
- Good, because delta linting removes the reason `categorical` was pinned to
  `warn`, so the gate can finally pause a write.
- Bad, because a blocking Stop gate can still show a bad draft once before the
  correction. This is inherent to the event, not to the implementation.
- Bad, because a third toggle layer makes "why is this value what it is" a
  three-file question. `cli.py toggle` output must name the winning layer.
- Neutral, because a forker sees no behavior change. Every default is unchanged
  and the new layer is absent without a content overlay.

## Confirmation

- `engine/setup/tests/toggles/test_content_layer.py` asserts the three-file
  precedence, including the case where the content file is absent.
- `engine/setup/tests/nervepack_engine/test_turn_gate.py` gains a case
  asserting `form=block` returns a `decision: block` payload whose reason
  forbids restating, and a case asserting `stop_hook_active` still short
  circuits before any file read.
- `engine/setup/tests/nervepack_engine/test_form_gate.py` gains a case
  asserting a Write onto an existing file with a legacy violation and a clean
  addition returns no finding.
- `grep -c '^SubagentStop' engine/setup/hooks.manifest` returns 1.

## Rollback

Every change is behind a toggle whose default is the current value. To disable
without reverting code, set in `~/.config/nervepack/toggles.local`:

```
turn_gate.form=warn
form_gate.categorical=warn
form_directive=off
turn_gate.subagent=off
```

To revert the code, `git revert` the merge commit and run
`python3 engine/nervepack_engine/cli.py setup install-hooks` to drop the new
hook rows from `~/.claude/settings.json`.

## Deviations

- 2026-08-28: self-review added a re-entrancy latch to `_content_conf_path` and
  three tests for it. Inside the declared blast radius, recorded because the
  guard defends against a failure that does not exist yet: `content_dir()` reads
  no toggle today, and would recurse forever if it ever did.
