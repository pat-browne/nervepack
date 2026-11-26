---
id: fix-dashboard-sidebar-wiki
status: accepted
date: 2026-11-26
tier: standard
blast_radius:
  - dashboard/index.html
  - engine/setup/tests/evaluator/test_dashboard_sidebar_layout.py
---

# fix-dashboard-sidebar-wiki: wiki list keeps its height

## Context and problem statement

The sidebar caps at 100vh. The jobs and credentials panels each took up to
45vh, so the wiki topic list shrank to a sliver.

## Considered options

1. Floor on the wiki list, shrinkable panels, credentials folded. Good, because
   topics stay visible and credentials stay one click away.
2. Move the health panels out of the sidebar. Bad, because it undoes a recent
   layout choice.

## Decision

We will give `.wikilist` a `min(40vh, 320px)` floor, let `.sidehealth` shrink
and scroll first, and render credentials in a closed `<details>`.

## Non-goals

Folding the jobs panel. It was not reported.

## Cross-cutting concerns

- Security: none. Values stay escaped.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because the wiki is usable again.
- Bad, because credential problems need a click to read.
