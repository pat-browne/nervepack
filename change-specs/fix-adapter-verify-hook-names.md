---
id: 0034
status: proposed
date: 2026-09-11
tier: normal
blast_radius:
  - engine/onboard/adapters/**
  - change-specs/fix-adapter-verify-hook-names.md
---

# 0034: adapter verify strings name retired hook scripts

## Context and problem statement

The three example adapters carry a `verify` command per capability. Two of them
grep for names that no longer exist.

`session-start` greps for `nervepack-session-directive`. `session-end-flush`
greps for `np-session-flush`. Both predate the bash to Python hook port.

`install-hooks` now writes `cli.py hook session-directive` and `cli.py hook
session-flush` into `settings.json`. A host wired by `cli.py onboard` fails both
greps.

The doctor then reports `session-start` and `session-end-flush` as MISSING. It
also reports `knowledge` and `scheduled-maint` as MISSING. A host with no
`adapter.json` fails every `check: adapter` capability at once.

This surfaced onboarding a fresh macOS box on 2026-09-10. The hooks, launchd
agents, and skill links were all correct. Only the strings were wrong.

A stale verify string is worse than a missing one. It reads as a real gap. It
sends the reader to re-run wiring that already works.

## Considered options

1. Correct the strings in the three examples.

   Good, because the doctor's report matches reality. Neutral, because an
   adapter already copied to a machine keeps its stale text until edited.

2. Make the doctor accept both old and new names.

   Bad, because it hides the drift. Bad, because it grows a compatibility branch
   for names nothing writes any more.

3. Generate `verify` from `hooks.manifest`.

   Good, because drift becomes impossible. Bad, because it couples the contract
   to one host's wiring format. The tool-neutral adapter design avoids that
   coupling on purpose.

## Decision

We will correct the two verify strings in all three example adapters.

Chosen option: "Correct the strings in the three examples". The examples should
match what `install-hooks` writes today. Option 3 would undo the host-neutrality
the adapter exists to provide.

The quoting changes too. `grep -q 'hook session-directive'` needs quotes,
because the match is now two words.

## Non-goals

Generating adapters from `hooks.manifest`. Option 3 stays open.

Migrating `adapter.json` files already on disk. A machine that copied the stale
example keeps it until someone re-copies. The doctor names the failing
capability, so the fix is discoverable.

## Cross-cutting concerns

- Security: none. The strings are read-only greps against a local file.
- Privacy: none.
- Observability: direct. Four false MISSING rows stop appearing.

## Consequences

- Good, because a correctly wired host now reads green.
- Good, because the SHOULD tier stops carrying noise that masks real gaps.
- Neutral, because existing per-machine adapters are untouched.

## Confirmation

`cli.py doctor` on a host wired by `cli.py setup install-hooks` reports
`session-start PASS` and `session-end-flush PASS`.

Verified on macOS 13.7.8 on 2026-09-11. Both greps were run against a real
`~/.claude/settings.json` before and after the change.

## Rollback

Not required at normal tier.

## Deviations

None. A `chmod +x` on `engine/setup/62-install-scheduled-auth-token.sh` was
carried here first and then removed. That path forces tier `high`, which this
doc fix does not warrant. The mode bit needs its own high-tier spec.
