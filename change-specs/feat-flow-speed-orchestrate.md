---
id: 0090
status: accepted
date: 2026-10-16
tier: normal
blast_radius:
  - skills/np-flow-speed/**
  - skills/np-flow-orchestrate/**
  - .claude-plugin/plugin.json
  - INDEX.md
  - engine/setup/nervepack-session-directive.md
  - change-specs/feat-flow-speed-orchestrate.md
---

# 0090: Speed and orchestrator flow skills

## Context and problem statement

Two workflows have no engine skill. In the first, one coordinator session
drives many tickets.

In the second, the user wants a change shipped with no questions. Without a
skill, sessions improvise the stop rules for both.

## Considered options

1. Two new engine skills plus two directive rows. Good, because each keeps its
   own triggers and stays small.

2. Extend `np-flow-develop`. Bad, because that skill lives in the overlay near
   its size budget.

## Decision

We will add `skills/np-flow-speed` and `skills/np-flow-orchestrate`. We will
register both and add two routing rows to the session directive.

## Non-goals

No hook, cron, or toggle. Both skills are guidance only.

## Cross-cutting concerns

- Security: speed mode lists the limits it never overrides.
- Privacy: no personal or company data in either skill.
- Observability: none.

## Consequences

- Good, because sessions reach a written stop rule for both modes.
- Bad, because the directive grows by two rows.

## Confirmation

A subagent given only each skill handles a sample scenario in line with it.

The `pii-guard` job and the regression suite pass.

## Deviations
