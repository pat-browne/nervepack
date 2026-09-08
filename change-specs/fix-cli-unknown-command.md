---
id: 0029
status: proposed
date: 2026-09-08
tier: normal
blast_radius:
  - engine/nervepack_engine/cli.py
  - engine/setup/tests/nervepack_engine/test_cli.py
  - change-specs/**
---

# 0029: An unrecognized cli.py command must fail loudly

## Context and problem statement

`cli.py` printed nothing and exited 0 for an unknown top-level verb, for a
bare invocation, and for an unknown `setup` step. A typo was therefore
indistinguishable from a successful no-op. Both #277 and #289 record the same
incident: `cli.py relink` and `cli.py index` were guessed, both "succeeded",
and `INDEX.md` shipped stale.

The inconsistency was the tell. Nested unknown names already reported —
`cron` and `hook` each log an unknown-name bail. Only the top level was
silent, and only `setup` swallowed a bad step name.

Fail-open (invariant 1) is right for a hook, where a crash must not block the
user. It is wrong for a command a human, a script, or an agent types, where
the exit code is the only signal that the work happened.

## Considered options

1. Exit non-zero on an unknown operator command, keep hook/cron fail-open —
   Good, because it splits on the distinction the codebase already draws in
   its own comments. Good, because no registered command changes behaviour.
   Neutral, because `cli.py hook <drifted-name>` stays a silent no-op.
2. Make every path strict, hooks included — Bad, because a Stop hook that
   exits non-zero can block a session, which is what invariant 1 exists to
   prevent. The drift it would catch is better caught in CI.
3. Leave it and document the trap — Bad, because #288 already did that and
   the trap kept biting.

## Decision

We will exit 2 with a stderr diagnostic and usage for a bare invocation, an
unknown top-level verb, and an unknown `setup` step. `--help`, `-h` and `help`
print the same usage to stdout and exit 0.

Hook and cron dispatch keeps returning 0. Instead, a test sweeps every
`cli.py hook|cron|setup <name>` reference in `hooks.manifest` and asserts it
resolves, so a drifted registration fails CI rather than no-opping at runtime.

Chosen option: "Exit non-zero on an unknown operator command", because it
fixes the reported defect without touching the session-lifecycle contract.

## Non-goals

Validating flags. `cli.py setup link-skills --verbose` still ignores the flag,
which #289 also notes. Argument parsing per command is a larger change and
does not share this fix's root cause.

Making `cli.py hook <unknown>` strict. See option 2.

## Cross-cutting concerns

- Security: none. Usage output lists command names already in the repo.
- Privacy: none.
- Observability: the existing `_bail` file log is unchanged; stderr is added
  for the operator paths, matching what `setup` already does for a failed step.

## Consequences

- Good, because a typo can no longer read as success under `set -e`.
- Good, because the command surface is discoverable from the CLI itself.
- Bad, because any caller that relied on a no-op exit 0 for an unknown verb
  now fails. The sweep found no such caller.
- Neutral, because `_COMMANDS` duplicates the dispatch chain; a test compares
  the two so they cannot drift.

## Confirmation

`engine/setup/tests/nervepack_engine/test_cli.py`: five tests covering bare
invocation, an unknown verb, an unknown setup step, `--help`, and the
`_COMMANDS`/dispatch-chain equality; plus
`test_every_registered_command_resolves`, which is the #289 sweep held open.
