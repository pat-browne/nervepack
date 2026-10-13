---
id: 0062
status: accepted
date: 2026-10-13
tier: normal
blast_radius:
  - engine/nervepack_engine/np_layout.py
  - engine/nervepack_engine/np_layout_cli.py
  - engine/nervepack_engine/np_sync.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/tests/layout/**
  - engine/setup/tests/sync/**
  - engine/setup/tests/evaluator/test_dashboard_build.py
  - dashboard/build.py
  - engine/onboard/**
  - skills/np-core-layout/**
  - skills/np-core-onboard/**
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - change-specs/layout-drift.md
---

# 0062: Layout drift detection and wiki nav for every routed kind

## Context and problem statement

A layer declares its routes once, in an interview. Content added later lands in
directories no route names, so contribution and the dashboard never see it.
`open_questions()` only checks top-level directories, and sync only validates the
manifest. The wiki nav reads only the `knowledge` route, so reference and roadmap
pages never show.

## Considered options

1. Re-run the full interview on every sync. Bad, because it needs a human.
2. Detect drift from frontmatter heads, route clear cases, ask about the rest.
   Good, because it is cheap and never guesses on mixed content.

## Decision

We will add `np_layout.drift()`, `add_route()`, and `apply_drift()`. Sync runs the
pass per layer behind param `sync.layout_drift` (default on), fail-open, stderr
only, and never commits. Onboarding runs `cli.py layout drift --apply`. The
dashboard builds nav groups from knowledge, reference, and roadmap routes and
skips a reference route nested in a folder-owning knowledge container.

Chosen option: "frontmatter-driven drift", because it keeps the manifest current
without guessing.

## Non-goals

Recording drift for a layer with no manifest. That layer still needs the interview.

## Cross-cutting concerns

- Security: new routes come from on-disk directory names and pass `validate()`.
- Privacy: reads only the first 2 KB of each page.
- Observability: one stderr line per change and per question.

## Consequences

- Good, because new typed directories become contribution targets on the next sync.
- Bad, because sync can edit a team layer's manifest in the working tree. The edit
  stays uncommitted for a human to review.
- Neutral, because `record()` keeps its read-only fallback to the per-machine cache.

## Confirmation

`engine/setup/tests/layout/test_np_layout_drift.py`,
`engine/setup/tests/sync/test_layout_drift_pass.py`, and the new
`TestWikiNavFollowsLayerLayout` cases in `test_dashboard_build.py`.

## Rollback

Set `sync.layout_drift=off`, or revert the PR.

## Deviations
