---
id: 0078
status: accepted
date: 2026-10-14
tier: normal
blast_radius:
  - dashboard/index.html
  - engine/setup/np_implement_suggestion.py
  - engine/setup/tests/evaluator/test_implement_target_routing.py
  - change-specs/np-suggest-include-log-file-path-in-the-session-com.md
---

# 0078: Show the implement log path in the dashboard

## Context and problem statement

A failed or unimplementable suggestion job gives the user no pointer to its log. They must guess where details live.

## Considered options

1. Carry the log path in the terminal status record and print it. Good, because it needs no new endpoint.
2. Add a log-viewer endpoint. Bad, because it adds server surface for a rare need.

## Decision

We will record the log path on every terminal implement status and print it with the done, failed and not-implementable messages.

Chosen option: 1, because it is the smallest change that answers "where do I look".

## Non-goals

Streaming or rendering the log in the dashboard.
