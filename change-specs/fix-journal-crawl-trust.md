---
id: 0104
status: proposed
date: 2026-10-29
tier: high
blast_radius:
  - engine/nervepack_engine/np_journal.py
  - engine/nervepack_engine/np_capture.py
  - engine/setup/tests/journal/**
  - agents/np-flow-episodic-maintain.md
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - change-specs/fix-journal-crawl-trust.md
---

# 0104: Treat journal crawl output as untrusted

## Context and problem statement

The journal crawl turns journal struggles and wins into capture-inbox records.
A journal is a Haiku summary of a transcript. The transcript can hold text the
session read from a web page, a file, or tool output.

Episodic-maintain distills inbox `struggles` and `strategies` into lessons.
Lessons are injected into future sessions and may carry an `enforce` block.
Text a session merely read can reach a later session as an instruction.

## Considered options

1. **Tag, sanitize, cap, and confine to corroboration** (chosen). Crawl items
   move to their own keys, and the maintain agent only uses them to add weight.

2. **Drop the crawl's struggles and wins.** Rejected, because the journal
   catches struggles that capture misses.

3. **Sanitize only.** Rejected, because a deny list can be bypassed and a
   structural rule holds when the filter misses.

## Decision

Every crawl record carries `mode: journal-crawl`. Its items are tagged
`source: journal-crawl` and sit under `crawl_struggles` and `crawl_strategies`.
They carry no `tool_match`, `topic_triggers`, or `destructive` field.

The crawl keeps at most 5 items per kind and clips each to 200 characters.

It drops any entry with a URL, a backtick or code fence, a shell command,
markup, a role prefix, hidden characters, or an imperative aimed at an agent.
The same filter covers the goal, progress, decisions, open questions, and next
step that form the note body.

It logs the dropped count and reasons, and writes them to `crawl_sanitize`.

The write guard covers the crawl keys. The maintain agent never creates a lesson
from `crawl_*` items alone. It never uses them for `enforce`, `tool_match`,
`gate`, or `topic_triggers`. It may only raise `seen` on a lesson that normal
capture items already support.

Model verdict: no model call is added.

## Non-goals

Resource purposes are out of scope. They are Haiku labels of 12 words or fewer
that land in a catalog no session injects.

A semantic injection detector is out. A false positive costs only a missed win.

## Cross-cutting concerns

- Security: closes a prompt-injection path from read text to lessons and gates.

- Privacy: no change. The scrub still runs at append.

- Observability: the crawl logs the dropped count per journal.

## Consequences

- Good, because an injected instruction in a journal cannot become a lesson.

- Bad, because wins that mention a command or a URL are dropped.

- Neutral, because the evaluator no longer counts crawl items as struggles.

## Confirmation

Class `TestCrawlTrust` proves each drop rule, the caps, the tags, the absence of
enforce fields, and the dropped-count log. Class `TestMaintainPromptRule` checks
that the agent prompt keeps the confinement rule.

## Rollback

1. Revert the merge commit. Old inbox records with `struggles` keys still drain
   as normal capture.

2. Records written under `crawl_*` keys before the revert stay in the inbox as
   unread keys and are ignored.
