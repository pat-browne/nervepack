---
id: 0110
status: proposed
date: 2026-11-01
tier: normal
blast_radius:
  - engine/nervepack_engine/np_scrub.py
  - engine/setup/tests/episodic/test_np_scrub_credentials.py
  - change-specs/fix-scrub-flag-list-dedup.md
---

# 0110: List the scrub credential flags once

## Context and problem statement

The credential flag names appeared in two lookaheads and one value pattern in
`np_scrub.py`. Adding a flag meant editing each copy, and a missed copy would
leave one rule redacting a flag the other still let through. Post-merge review
of spec 0109 raised it, along with an unexplained `(?i)` and lookbehind
interaction and a misleading test comment.

## Considered options

1. Build the patterns from one constant. Good, because one edit covers all rules.
2. Leave the copies and add a test that compares them. Bad, because it guards the
   duplication instead of removing it.

## Decision

We will define `_CRED_FLAGS`, `_NEXT_CRED_FLAG` and `_FLAG_VALUE` once and build
both flag rules from them. Matching behavior does not change. We will also
explain the `(?i)` and lookbehind interaction in the rule comment and reword the
test comment.

Chosen option: 1.

## Non-goals

- No new redaction cases.
- No logging in the scrubber. It handles secrets and must not write its input.

## Cross-cutting concerns

- Security: none, because the patterns match the same text as before.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because a new credential flag is one edit.
- Neutral, because the rule list reads slightly more indirectly.

## Confirmation

The 41 tests in `test_np_scrub_credentials.py` and `test_np_capture.py` pass
unchanged, and `test_scrub.sh` still passes.

## Rollback

Revert this PR.

## Deviations
