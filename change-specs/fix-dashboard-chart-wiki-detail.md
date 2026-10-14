---
id: 0084
status: accepted
date: 2026-10-14
tier: normal
blast_radius:
  - dashboard/index.html
  - dashboard/build.py
  - engine/setup/np_dashboard_actions.py
  - engine/setup/tests/evaluator/test_dashboard_build.py
  - engine/setup/tests/evaluator/test_dashboard_panels_static.py
  - docs/ARCHITECTURE.md
  - change-specs/fix-dashboard-chart-wiki-detail.md
---

# 0084: Round chart dots, collapsed wiki layers, row detail text

## Context and problem statement

The Trend and Token charts use a fixed 1000-unit viewBox with non-uniform
scaling. In a two-up cell the dots render as tall ovals.

The Trend card also leaves empty space under its legend. The wiki nav opens one
level on load, which buries the layer rows.

Graduation candidates and compact proposals show only a title, so a reviewer
cannot read what they approve.

## Considered options

1. Keep the fixed viewBox and draw dots as HTML only. Bad, because the line still stretches.
2. Size the viewBox to the wrapper's pixel size on render and resize. Good, because the scale is 1:1.
3. A detail pane for row text. Bad, because no other panel uses one.
4. An expandable row. Good, because it keeps the reader in place.

## Decision

We will set the chart viewBox from the wrapper's pixel size, redrawn by a
ResizeObserver. In a two-up row the chart grows to fill the cell.

The wiki nav starts with every level collapsed, and search still opens matches.

Graduation and proposal rows expand to show their full text. The dashboard
build adds the lesson file text to each candidate. The proposal parser adds the
entry text.

Chosen options: "pixel viewBox" and "expandable row".

## Non-goals

Rendering the detail text as Markdown. Changing graduation or proposal actions.

## Cross-cutting concerns

- Security: detail text passes through `esc()`. A candidate name with a path separator is skipped.
- Privacy: the text already lives in the local content overlay and reaches only the local data file.
- Observability: none.

## Consequences

- Good, because dots stay round and the text is readable before approval.
- Bad, because the data file grows by up to 20 KB per row.

## Confirmation

`test_dashboard_panels_static.TestChartAspectAndDetailRows`,
`test_dashboard_build.TestWikiLayersStartCollapsed`, and
`test_dashboard_build.TestDetailBodies`.

## Rollback

Revert the squash commit.

## Deviations
