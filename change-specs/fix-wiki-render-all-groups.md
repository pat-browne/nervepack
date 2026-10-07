---
id: 0050
status: accepted
date: 2026-10-07
tier: normal
blast_radius:
  - dashboard/build.py
  - engine/setup/tests/evaluator/test_dashboard_build.py
  - change-specs/fix-wiki-render-all-groups.md
---

# 0050: Render wiki pages for every declared route group

## Context and problem statement

`render_pages` wrote HTML only for the `topics` and `concepts` groups. A layer that
declares other knowledge routes (data-base's `data-model` variant) got nav entries
whose pages were never written, so every click returned not found. 64 of 198 nav
links were broken on a real install.

## Considered options

1. Walk every group in the index. Good, because the nav and the renderer read one list.
2. Add `data-model` as a third hardcoded group. Bad, because the next declared route breaks again.

## Decision

We will render every group in `index["groups"]`, and fall back to topics and
concepts for an index built before groups existed.

Chosen option: "walk every group", because it removes the mismatch at its source.

## Non-goals

Adding reference or roadmap routes to the nav. That is separate work.

## Cross-cutting concerns

- Security: no new sink. Pages still render through `md_to_html`.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because every nav link has a page.
- Neutral, because render time grows with the pages a layer already declares.

## Confirmation

`TestWikiNavFollowsLayerLayout.test_nonstandard_route_pages_are_rendered`.
A real-content build had 0 missing pages of 198 links.

## Rollback

Revert this PR. The renderer falls back to the old topics/concepts walk.

## Deviations
