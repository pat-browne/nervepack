---
id: 0087
status: accepted
date: 2026-10-15
tier: normal
blast_radius:
  - dashboard/index.html
  - engine/setup/tests/evaluator/test_dashboard_build.py
  - change-specs/fix-dashboard-wiki-tokens.md
---

# 0087: Open wiki layers and one-row token stats

## Context and problem statement

The wiki nav loads with every level collapsed, so readers see only layer rows
and must click to find the groups. The token card splits its five stats over
two rows, which does not match the sibling trend card.

## Considered options

1. Open layers on load, keep groups collapsed. Good, because groups show at a glance.
2. Open every level. Bad, because long topic lists bury the layer rows.

## Decision

We will render layer sections open on load. Groups below follow search as before.
The token card keeps its five stats in one strip with a tighter gap that wraps when narrow.

Chosen option: "Open layers on load", because it shows structure without long lists.

## Non-goals

Changing the est.-saved row or the chart.

## Cross-cutting concerns

- Security: none.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because groups are visible without a click.
- Neutral, because users can still collapse a layer.

## Confirmation

`TestWikiLayersStartExpanded` in `engine/setup/tests/evaluator/test_dashboard_build.py`.
Screenshots at 400px and 1400px.

## Rollback

Revert the squash commit.

## Deviations
