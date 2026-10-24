---
id: 0089
status: accepted
date: 2026-10-15
tier: normal
blast_radius:
  - dashboard/index.html
  - engine/setup/tests/evaluator/test_dashboard_panels_static.py
  - change-specs/fix-token-chart-axis.md
---

# 0089: Token usage chart scale and two-up alignment

## Context and problem statement

The token usage chart mapped output tokens onto a log domain fixed at 1 to max.
Session output runs from about 100 to about 30k, so the low half of the plot sat
empty and the dots floated in a thin band. The chart had no gridlines or labels,
so the "log scale" label could not be read. Its height also differed from the
contribution chart beside it.

## Considered options

1. Switch to a linear scale. Bad, because the data spans more than two decades and
   one outlier would flatten the rest.
2. Keep log, fit the domain to the data and add labelled 1-2-5 ticks. Good, because
   the dots fill the plot and the scale reads at a glance.

## Decision

We will keep the log scale and compute the domain from the data min and max, padded
10% in log space. We will label decade gridlines (1-2-5 ticks when fewer than two
decades fit). Both two-up charts get labelled gridlines, a shared left gutter and a
fixed 180px plot height pinned to the card bottom.

Chosen option: "Keep log, fit the domain", because the data range justifies log.

## Non-goals

No change to the token data, the tooltip content or the stat strips.

## Cross-cutting concerns

- Security: none, render-only change.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because both charts fill their plot and share height, legend and baseline.
- Neutral, because the trend chart now shows 0/33/67/100 tick labels.

## Confirmation

`TestTokenChartScale` in `engine/setup/tests/evaluator/test_dashboard_panels_static.py`,
plus before and after screenshots at 1400px and 400px.

## Rollback

Revert the squash commit.

## Deviations
