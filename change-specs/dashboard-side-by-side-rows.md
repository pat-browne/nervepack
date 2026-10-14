---
id: 0079
status: accepted
date: 2026-10-14
tier: standard
blast_radius:
  - dashboard/index.html
  - engine/setup/tests/evaluator/test_dashboard_panels_static.py
  - change-specs/dashboard-side-by-side-rows.md
---

# 0079: Two-up rows for the performance charts and the ledger

## Context and problem statement

The two performance charts stack as full-width panels. So do the Change Ledger
and Latest Session panels. On a wide screen this wastes width and pushes content
below the fold.

## Considered options

1. Reuse the existing `.grid` two-up class. Good, because it already stacks on
   narrow viewports and the wins/assets row uses it.
2. Add a new flex row class. Bad, because it duplicates `.grid`.

## Decision

We will wrap each pair in a `.grid` row and give grid cells `min-width:0` so
charts and tables shrink inside a cell.

Chosen option: "Reuse `.grid`", because it matches the existing idiom.

## Non-goals

Changing the `.grid` breakpoint (900px). It already stacks below 768px.

## Cross-cutting concerns

- Security: none.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because both rows use the width on desktop.
- Neutral, because narrow viewports keep the stacked layout.

## Confirmation

`TestTwoUpRows` in `engine/setup/tests/evaluator/test_dashboard_panels_static.py`.

## Rollback

Revert the commit.

## Deviations
