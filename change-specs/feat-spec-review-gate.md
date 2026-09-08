---
id: 0027
status: accepted
date: 2026-09-07
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/spec_review.py
  - engine/nervepack_engine/cli.py
  - engine/setup/hooks.manifest
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/allowlist-entries.txt
  - engine/nervepack_engine/np_toggle.py
  - engine/setup/tests/**
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - change-specs/**
  - skills/np-core-doctor/references/log-patterns.md
---

# 0027: move the spec/plan review gate off the write and onto the implementation

## Context and problem statement

Writing a spec or a plan raises a permission dialog. `Write` is not allowlisted,
so every `docs/superpowers/specs/*.md` and `docs/superpowers/plans/*.md` file
costs an approval before it exists. The dialog asks the wrong question. It asks
whether the agent may create a document, at the one moment when creating the
document is the whole point and nothing irreversible has happened.

The question worth asking arrives later. Once a spec exists, the risk is that
implementation starts against a spec no human has read. `brainstorming` states
that gate in prose, and prose is a gate a session can talk itself out of. The
same failure mode is already recorded twice in this repo, and it is why
`drift_guard` exists as a hook rather than a paragraph.

A machine-scoped escape hatch is also missing. Every `gates.*` key today is
shared scope, so turning a gate off on one laptop turns it off on every machine
that syncs the content overlay.

## Considered options

1. **Allowlist the spec and plan paths, and add a PreToolUse hook that asks once
   before the first implementation edit** — Good, because the approval lands
   where a wrong answer is expensive instead of where it is free. Good, because
   the hook is self-scoping: a repo with no spec for the branch never sees it.
   Good, because it gives `gates` its first review-time consumer without
   touching the CI gates. Bad, because it adds a third interrupting hook.
2. **Edit the superpowers `brainstorming` skill to drop the review gate** — Bad,
   because the plugin cache is overwritten on update, so the change survives
   until the next `claude plugin update` and no longer. Bad, because it deletes
   the gate rather than moving it.
3. **Set `permissions.defaultMode` to `acceptEdits`** — Bad, because it removes
   the prompt for every write in every repo, not for specs and plans. Ceding the
   whole surface to remove one dialog is not a trade worth making.

## Decision

We will allowlist writes and edits under `docs/superpowers/specs/`,
`docs/superpowers/plans/` and `change-specs/`, and add a `spec-review`
PreToolUse hook on `Write` and `Edit` that asks once, before the first
implementation edit on a branch whose spec has not been confirmed as reviewed.

Chosen option: "allowlist the paths, gate the implementation", because it moves
one approval from a moment that carries no risk to the moment the risk appears,
and because a hook is the only form of this gate that a session cannot argue
its way past.

The hook reads a new local-scope toggle row, `gates.spec_review`. Local scope
routes `cli.py toggle gates.spec_review off` to
`~/.config/nervepack/toggles.local`, so one machine can opt out without
changing what the other machines enforce. It does not reuse
`gates.spec_guard.enforce`: that key is reserved by
`np-flow-develop/references/hooks.md` for the local spec-guard pre-check, a
validation gate rather than a review gate, and one key answering two questions
cannot be turned off for one of them.

Receipts are keyed on session, spec path and spec mtime. Editing the spec
invalidates the receipt, so a spec rewritten mid-branch is confirmed again.

## Non-goals

- Validating the spec's contents. `spec-guard` in CI owns that, and duplicating
  its field checks here would put two implementations of one policy on two
  sides of a round trip.
- Enforcing that a spec exists. A repo with no spec for the branch is silent.
  A gate that demands a spec for every change gets disabled, and a disabled gate
  protects nothing.
- Reaching CI. Local toggles are not readable from a GitHub runner. The
  CI-side equivalent stays the ruleset bypass-actor list.

## Cross-cutting concerns

- Security: the allowlist entries widen write permission to three directory
  patterns under `~/Code`. They are documentation paths, and the entries are
  managed, so `toggle allowlist off` removes exactly them.
- Privacy: the log records a repo-relative spec path and a session id. No file
  contents.
- Observability: one line per adjudication in `spec-review.log`, decoded by
  np-core-doctor's `references/log-patterns.md`. The hook logs whatever the
  toggle says, so an override is never silent.

## Consequences

- Good, because writing a spec or a plan stops costing an approval.
- Good, because the approval that remains asks a question whose answer matters.
- Bad, because a third PreToolUse hook can interrupt. Bounded by asking once per
  spec revision per session rather than once per edit.
- Neutral, because the hook is inert in every repo that has no `change-specs/`
  entry for the current branch, which is every repo but this one today.

## Blast radius

Declared in the frontmatter. The hook, its CLI dispatch row, its manifest rows,
the two toggle files, the allowlist entries, the tests, and the three documents
that the doc-coupling triggers `lifecycle-hooks` and `toggles` require.

## Confirmation

- `engine/setup/tests/run-all.sh` passes, including the new
  `test_spec_review.py`.
- `cli.py setup install-hooks` registers both `spec-review` rows, confirmed by
  reading `~/.claude/settings.json` back.
- `cli.py toggle allowlist on` puts the six path entries in
  `permissions.allow`, confirmed the same way.
- Piping a synthetic PreToolUse payload for a spec-file write returns empty, and
  one for an implementation-file write on a branch with an unreviewed spec
  returns an `ask` decision.
- `cli.py toggle gates.spec_review off` writes the key to
  `~/.config/nervepack/toggles.local` and the same payload then returns empty.

## Deviations

**Widened to `engine/nervepack_engine/np_toggle.py`.** Verifying the
Confirmation step "`cli.py toggle allowlist on` puts the six path entries in
`permissions.allow`" showed that it does not, and never has. `flip()` routes to
`managed()` when the **scope** column reads `managed`, but `toggles.conf`
declares `allowlist|local|managed|on|` — `local` scope, `managed` enforcement,
exactly as the file's own header documents. So `install_permissions()` has had
no production caller; `test_allowlist.py` calls it directly, which is why a
green suite never surfaced the gap.

Left unfixed, this change ships entries that reach no machine but the one they
were installed on by hand, which is the opposite of the portability rule. The
fix reads the enforce column as well as the scope column, and keeps the old
scope check so a row that puts `managed` there still routes the same way.

## Rollback

`cli.py toggle gates.spec_review off` disables the hook immediately with no
deploy. `cli.py toggle allowlist off` then `on` re-syncs the permission entries.
Reverting this commit and re-running `cli.py setup install-hooks` removes the
manifest rows; the stale settings.json entries are dropped by
register-by-basename on that run.
