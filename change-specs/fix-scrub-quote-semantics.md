---
id: 0109
status: proposed
date: 2026-10-31
tier: normal
blast_radius:
  - engine/nervepack_engine/np_scrub.py
  - engine/setup/tests/episodic/test_np_scrub_credentials.py
  - change-specs/fix-scrub-quote-semantics.md
---

# 0109: Match shell quoting in the credential-flag scrub rules

## Context and problem statement

The credential-flag rules from spec 0107 treated single quotes like double quotes and
stopped after one quoted piece. A shell does neither. `--password "pw\" --token "s3cret"`
is one word, so a value cut at the first piece left `s3cret` visible. The
`Authorization=Basic` rule used `\b`, which does not fire after `_`, so
`http_authorization=basic ...` passed through. A security review of the merged code
flagged both.

## Considered options

1. Keep the escape-aware quotes and loop the match. Good, because it follows shell rules.
2. Drop escape support. Bad, because `"abc\"def"` then leaks its tail.
3. Re-run all rules to a fixed point. Bad, because it hides rather than fixes the bad match.

## Decision

We will match the value as one or more shell word pieces: double-quoted with escapes,
single-quoted and literal, or a run of other non-space characters. An unquoted run stops
only before a separator that leads into another credential flag (`--password`, `--token`,
`-u` and the like), so a password that merely contains `;-` is fully redacted. The
`-u`/`--user` rule uses the same value shape. The `Authorization` rule is case-insensitive
and blocked only by a preceding letter.

Chosen option: 1.

## Non-goals

- Backticks, `$(...)` and heredocs. A scrubber cannot parse these safely.
- Glued `-p<password>`. See spec 0107.

## Cross-cutting concerns

- Security: widens redaction only. A value is never shortened relative to spec 0107 except
  at a following credential flag, which its own match redacts.
- Privacy: fewer secret-shaped strings reach committed memory.
- Observability: none.

## Consequences

- Good, because the rules agree with what a shell reads as one word.
- Bad, because a long run of adjacent pieces redacts more text than strictly needed.
- Neutral, because the scrubber stays fail-open.

## Confirmation

`test_np_scrub_credentials.py` covers the escaped-quote chain from the review, literal
single quotes, `;-` inside a password, prefixed `Authorization` names, and the existing
cases. `test_scrub.sh` still passes.

## Rollback

Revert this PR.

## Deviations
