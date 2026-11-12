---
id: 0117
status: accepted
date: 2026-11-12
tier: high
blast_radius:
  - engine/**
  - docs/ARCHITECTURE.md
  - skills/np-flow-speed/**
  - change-specs/speed-mode-silences-gates.md
---

# 0117: Speed mode silences the spec-review gate

## Context and problem statement

Sessions running np-flow-speed are meant to move fast, but the spec-review ask
still interrupts them.

## Considered options

1. Silence spec-review for sessions marked as speed mode — Good, because speed sessions are not interrupted; Bad, because it adds a marker hook.
2. Leave the gates as they are — Good, because no change; Bad, because speed sessions stay interrupted.

## Decision

We will mark speed-mode sessions with a per-session file and have spec-review skip when it is present and `gates.speed_silent` is on.

Chosen option: "Silence spec-review", because the marker is cheap and every error path fails open to the normal verdict.

## Non-goals

Silencing drift-guard, whose deny blocks the agent, not the human; any other gate; a speed-mode exemption for secret or PII guards.

## Cross-cutting concerns

- Security: errors answer "not speed mode", so gates keep their normal verdict.
- Trust: an agent with shell access can still write the marker file directly, as it can edit toggles.local. The gate guards against accidental prompts, not a hostile agent. Markers expire after `gates.speed_silent_ttl_h` hours (default 12).
- Forgery: the hook payload comes from the harness, so an agent cannot forge a UserPromptSubmit event. speed-mark also requires a transcript file under ~/.claude/projects whose session segment equals session_id, and writes no marker otherwise. The remaining risk is a direct file write, noted above.
- Privacy: the marker holds only a session id under the local cache.
- Observability: each skip logs one `SKIP ... speed mode` line.

## Consequences

- Good, because speed sessions run uninterrupted.
- Bad, because one more Python process runs per prompt and Skill call.
- Neutral, because the toggle defaults on and can be turned off per machine.

## Rollback

Set `gates.speed_silent=off` in toggles, or revert the PR. Markers expire after 12 h.

## Confirmation

`engine/setup/tests/nervepack_engine/test_speed_silence.py`.

## Deviations

None.
