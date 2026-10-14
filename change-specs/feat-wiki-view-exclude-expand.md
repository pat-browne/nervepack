---
id: 0079
status: accepted
date: 2026-10-14
tier: normal
blast_radius:
  - dashboard/build.py
  - dashboard/index.html
  - engine/setup/tests/evaluator/test_dashboard_build.py
  - change-specs/feat-wiki-view-exclude-expand.md
---

# 0079: Wiki view drops record groups and opens one level

## Context and problem statement

The dashboard wiki nav lists every declared route as a group. Receipts,
meetings, and plans are record streams, not reading, and crowd the nav. Inside
a layer section only the first group opened, so most groups hid behind a click.

## Considered options

1. Filter at build time from one named constant. Good, because the data never
   reaches the page and the list lives in one place.
2. Filter in index.html. Bad, because the pages still render and ship.

## Decision

We will drop any variant whose heading or container dir name matches
`WIKI_EXCLUDED_GROUPS` (receipts, meetings, plans), case-insensitively, in
`build.py` `_scan_plan()`. We will open every group inside a layer by default.
Deeper levels stay collapsed until a search runs.

Chosen option: "Filter at build time", because it keeps the list in one place.

## Non-goals

A per-machine toggle param for the list. No user has asked to tune it.

## Cross-cutting concerns

- Security: none.
- Privacy: fewer record pages render to disk.
- Observability: none.

## Consequences

- Good, because the nav shows reading content only.
- Neutral, because a layer that wants these groups back must edit the constant.

## Confirmation

`TestWikiExcludedGroups` and `TestWikiLayerExpandsOneLevel` in
`engine/setup/tests/evaluator/test_dashboard_build.py`.

## Rollback

Revert the squash commit.

## Deviations
