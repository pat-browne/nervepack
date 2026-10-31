---
id: 0108
status: proposed
date: 2026-10-25
tier: normal
blast_radius:
  - skills/np-core-capture-learning/**
  - skills/np-core-contribute/SKILL.md
  - skills/np-core-dispatch/**
  - skills/np-flow-orchestrate/SKILL.md
  - skills/np-flow-speed/SKILL.md
  - agents/np-flow-episodic-maintain.md
  - engine/nervepack_engine/np_capture.py
  - engine/setup/tests/episodic/test_np_capture.py
  - docs/ARCHITECTURE.md
  - INDEX.md
  - change-specs/feat-flows-prime-capture-stack-wiki.md
---

# 0108: Subagents prime from nervepack and capture stack facts

## Context and problem statement

Subagents start with no nervepack context and nothing tells them to save what
they learn. Capture also records rules and failures, not how a tech stack
behaves, so the wiki does not grow as code ships.

## Considered options

1. A new cron or hook that mines sessions for stack facts. Bad, because it adds
   a job beside capture and episodic-maintain, which already read every session.
2. Add `stack_facts[]` to the existing capture call and stage it in
   `episodic-maintain`. Good, because the back-capture sweep already covers
   dead sessions. Bad, because staged facts wait for a human.
3. Let `episodic-maintain` write to `wiki/` directly. Bad, because the wiki is
   human-reviewed and the agent's mandate covers `memory/` only.

## Decision

We will add `stack_facts[]` to the capture prompt. `episodic-maintain` §5c
stages each fact in `memory/stack-facts/<stack>.md` and flags stacks ready for
the wiki. A human promotes them through `np-core-contribute`.

We will also put a prime block and a capture block, including an in-session
stack sweep, in every dispatched brief. The sweep writes to the wiki directly
because a session is attended.

Chosen option: 2, because it reuses the jobs that already run.

## Non-goals

- No new cron, hook or launchd job.
- No unattended write to `wiki/`.
- No `wiki` kind for `nervepack_recall`. Tracked as a follow-up.

## Cross-cutting concerns

- Security: stack facts pass through `np_scrub` with the rest of the note.
- Privacy: the prompt excludes one project's own details.
- Observability: the existing capture log. Maintain reports promotion candidates.

## Consequences

- Good, because every session feeds the stack wiki without a new job.
- Bad, because one more field raises the capture call's output size.
- Neutral, because a missing `stack_facts` key is read as empty.

## Confirmation

`test_np_capture.py` `test_8b` asserts `stack_facts[]` survives capture and
redaction. The skill-listing lint passes on the engine tree.

## Rollback

Revert this PR. Notes already in the inbox keep an unused `stack_facts` key,
which no reader rejects. Delete `memory/stack-facts/` in the content overlay.

## Deviations
