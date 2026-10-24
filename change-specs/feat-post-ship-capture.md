---
id: 0088
status: proposed
date: 2026-10-15
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/post_ship_capture.py
  - engine/nervepack_engine/cli.py
  - engine/setup/hooks.manifest
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/np_toggle_audit.py
  - engine/setup/nervepack-session-directive.md
  - engine/setup/tests/nervepack_engine/test_post_ship_capture.py
  - engine/setup/tests/setup/test_install_hooks.py
  - skills/np-core-capture-learning/SKILL.md
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - change-specs/feat-post-ship-capture.md
---

# 0088: Post-ship learning capture hook

## Context and problem statement

A PR merge or a deploy is when a change's lessons are freshest. It is also when
a session most often ends. Capture depends on the user asking for it, so most
of those lessons are lost.

## Considered options

1. PostToolUse Bash hook that detects a ship command and injects a prompt. Good,
   because it is deterministic and cheap. Bad, because detection is a regex list.
2. A Stop hook that scans the turn transcript. Bad, because it fires after the
   reader saw the reply and needs the transcript parser.
3. A routing row in the directive only. Bad, because a passive list does not get used.

## Decision

We will add `post_ship_capture.py`, a PostToolUse hook on matcher `Bash`. It
matches the command against `SHIP_PATTERNS` and skips a failed result. On a hit
it returns `additionalContext` telling the session to invoke
`np-core-capture-learning` before ending the turn.

Chosen option: 1, because it puts the prompt in front of the model at the
moment of shipping with no model call.

## Non-goals

- No automatic capture. The session still decides what is worth keeping.
- No detection of a bare `git push` on main. The branch is not in the command.

## Cross-cutting concerns

- Security: reads only the hook payload. No shell-out, no file write beyond the
  existing session-signal marker.
- Privacy: the injected text names only the matched label, never the command.
- Observability: a `post-ship-capture` marker lands in the session-signal log.

## Consequences

- Good, because merges and deploys now end with a capture step by default.
- Bad, because a false positive costs one extra skill call.
- Neutral, because the toggle `post_ship` turns it off.

## Confirmation

`engine/setup/tests/nervepack_engine/test_post_ship_capture.py` covers merge
hits, deploy hits, failure skipped, unrelated commands skipped, and toggle off.
`test_install_hooks.py` asserts the `Bash` PostToolUse registration.

## Rollback

Run `cli.py toggle post_ship off` for an immediate stop. To remove it, revert
this PR and re-run `cli.py setup install-hooks`. Then delete the PostToolUse
`post-ship-capture` entry from `~/.claude/settings.json`, as register does not
purge removed rows.

## Deviations
