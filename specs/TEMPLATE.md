---
id: <NNNN>
status: proposed | rejected | accepted | superseded by <NNNN>
date: YYYY-MM-DD
tier: standard | normal | high
blast_radius:
  - path/glob/**
---

# <NNNN>: <short noun phrase>

## Context and problem statement

<The forces at play, in value-neutral language. Describe the tension, not the
answer.>

## Considered options

1. <option> — Good, because ... / Bad, because ... / Neutral, because ...
2. <option> — ...

## Decision

We will <active voice, full sentences>.

Chosen option: "<title>", because <justification>.

## Non-goals

<What could reasonably be a goal and is deliberately not one, with the reason.>

## Cross-cutting concerns

- Security:
- Privacy:
- Observability:

## Consequences

- Good, because ...
- Bad, because ...
- Neutral, because ...

## Confirmation

<How compliance with this decision will be verified: a named test, an
assertion, a grep, a CI job.>

## Rollback

<High tier only. How to return to the last known-good state.>

## Deviations

<Append here when implementation leaves the declared blast radius. Each entry:
date, what was touched outside blast_radius, and the one-line reason. Never
delete a prior entry.>
