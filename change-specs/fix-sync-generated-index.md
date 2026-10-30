---
id: 0105
status: accepted
date: 2026-10-29
tier: high
blast_radius:
  - engine/nervepack_engine/np_sync.py
  - engine/setup/tests/sync/test_np_sync.py
  - skills/np-core-sync/references/outcomes.md
  - change-specs/fix-sync-generated-index.md
---

# 0105: Sync drops regenerated INDEX.md rows before it pulls

## Context and problem statement

`np_sync` runs `link-skills` after a pull, and `link-skills` rewrites `INDEX.md`.
Nothing commits the rewrite, so the file stays dirty.

The next sync then skips the pull. The engine reports `SKIPPED (dirty)`. A content layer reports "local edits". Each cycle needed a person to discard the file by hand.

## Considered options

1. Stop sync from regenerating `INDEX.md`. Good, because the file stays clean. Bad, because the index goes stale until the next contribute step.

2. Discard `INDEX.md` whenever it is the only dirty file. Good, because it is simple. Bad, because a hand-edited heading is lost without notice.

3. Discard it only when its diff touches table rows. Good, because regenerated output is exactly that. Neutral, because a hand-edited row is also dropped, and the generator rebuilds rows anyway.

## Decision

We will drop a dirty `INDEX.md` before a pull in one case. It must be the only changed file. Its diff must touch table rows only.

We apply this to the engine and to every content or team layer that sync fast-forwards.

Chosen option: 3, because it matches what the generator writes. Every other case stays with the user.

When the heading or prose changed, sync skips the pull. It names `INDEX.md` in the status line. The user then decides which copy is current.

## Non-goals

- We do not change `link-skills` or the generator.

- We do not discard any other dirty file, ever.

- We do not discard when the layer is level with or ahead of its upstream.

## Cross-cutting concerns

- Security: none. The change only runs `git checkout -- INDEX.md` inside repos sync already manages.

- Privacy: none.

- Observability: the engine status line gains an `INDEX.md` hint on a skip. The layer note names `INDEX.md` too. Each drop writes one stderr line, and a failed drop writes another.

## Consequences

- Good, because sync no longer stalls on a regenerated index.

- Bad, because a hand edit confined to table rows is dropped on the next pull.

- Neutral, because the post-pull relink dirties the file again until the next sync.

## Confirmation

`engine/setup/tests/sync/test_np_sync.py` holds six tests.

They cover a row edit that fast-forwards, in the engine and in a content layer. They cover a skip on a prose edit. They cover a skip with other dirty files. They cover a level tree left alone.

## Rollback

Revert the commit. Sync returns to skipping on any dirty file. No data migration.

## Deviations
