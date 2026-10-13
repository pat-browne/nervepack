---
id: 0064
status: accepted
date: 2026-10-13
tier: normal
blast_radius:
  - skills/np-core-research/**
  - .claude-plugin/plugin.json
  - INDEX.md
  - engine/setup/nervepack-session-directive.md
  - change-specs/skill-np-core-research.md
---

# 0064: A research skill for multi-source technical questions

## Context and problem statement

Several wiki sessions used the same method: fan out agents, keep official
pinned sources, check currency, record negative results and limits, then
synthesize. The method lived only in `log.md` entries. Sessions that needed
external facts fell back to model memory.

## Considered options

1. A new `np-core-research` skill plus a directive routing row. Good, because
   every session and flow can reach it.
2. Extend `np-core-contribute`. Bad, because contribute files knowledge and
   does not gather it.

## Decision

We will add `skills/np-core-research`, register it, and add one routing row to
the session directive.

## Non-goals

No new hook, cron, or toggle. The skill is guidance only.

## Cross-cutting concerns

- Security: none.
- Privacy: no personal data. The skill names no instance content.
- Observability: none.

## Consequences

- Good, because research output becomes checkable and fileable.
- Bad, because the directive grows by one row.

## Confirmation

A subagent given only the skill answers a sample question with all five output
sections. `pii-guard` and the regression suite pass.

## Deviations
