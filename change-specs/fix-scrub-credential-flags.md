---
id: 0107
status: proposed
date: 2026-10-29
tier: normal
blast_radius:
  - engine/nervepack_engine/np_scrub.py
  - engine/setup/tests/episodic/test_np_scrub_credentials.py
  - change-specs/fix-scrub-credential-flags.md
---

# 0107: Scrub credentials in command lines and URLs

## Context and problem statement

`np_scrub` redacts known token shapes and `key=value` pairs. It misses
`--password hunter2` style flags, `curl -u user:pw` and Basic auth
headers. Capture now stores `stack_facts[].evidence`, which often holds a
command line, so these shapes reach committed memory. The security review of
nervepack#424 flagged the gap.

## Considered options

1. Scrub only inside `stack_facts`. Bad, because `body` and `struggles` hold the same shapes.
2. Add rules to `np_scrub`. Good, because every capture path shares it.
3. Drop `evidence` entirely. Bad, because the claim loses its proof.

## Decision

We will add three rules to `np_scrub._RULES`: long credential
flags, `-u`/`--user` pairs, and Basic auth values. Flag names must end at `=`
or whitespace, so `--token-file` and `--password-stdin` stay untouched.

Chosen option: 2.

## Non-goals

- Glued `-p<password>`. Too many tools use `-p` for a port or path.
- Docker `login -p`. Same reason.

## Cross-cutting concerns

- Security: widens redaction only.
- Privacy: fewer secret-shaped strings reach committed memory.
- Observability: none.

## Consequences

- Good, because one fix covers every capture path.
- Bad, because a rare false positive redacts a harmless string.
- Neutral, because the scrubber stays fail-open.

## Confirmation

`test_np_scrub_credentials.py` covers each shape, the untouched look-alikes,
and the existing rules. `test_scrub.sh` still passes.

## Rollback

Revert this PR.

## Deviations
