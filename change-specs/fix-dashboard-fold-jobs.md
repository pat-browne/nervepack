---
id: 0126
status: accepted
date: 2026-11-26
tier: normal
blast_radius:
  - dashboard/index.html
  - engine/setup/tests/evaluator/test_dashboard_sidebar_layout.py
---

# 0126: health checks panel starts folded

## Context and problem statement

Spec 0125 folded the credentials panel. The health checks panel still opened
in full and took sidebar space from the wiki.

## Considered options

1. Fold it the same way as credentials. Good, because both panels behave alike.
2. Leave it open. Bad, because Pat asked for the fold.

## Decision

We will render health checks in a closed `<details class="sidefold">`. The
credentials fold takes the same class. A refresh keeps an open fold open.

## Non-goals

Moving the panels out of the sidebar.

## Cross-cutting concerns

- Security: none. Values stay escaped.
- Privacy: none.
- Observability: the summary line still shows error, warning and overdue counts.

## Consequences

- Good, because the wiki keeps the sidebar.
- Bad, because a failing job needs a click to see its Troubleshoot button.
