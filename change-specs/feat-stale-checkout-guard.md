---
id: 0095
status: accepted
date: 2026-10-24
tier: standard
blast_radius:
  - engine/nervepack_engine/np_checkout_guard.py
  - engine/nervepack_engine/hooks/checkout_guard.py
  - engine/nervepack_engine/cli.py
  - engine/nervepack_engine/np_doctor.py
  - engine/onboard/capabilities.json
  - engine/setup/hooks.manifest
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/tests/nervepack_engine/test_checkout_guard.py
  - docs/ARCHITECTURE.md
  - change-specs/feat-stale-checkout-guard.md
---

# 0095: stale-checkout guard

## Context and problem statement

Sessions read wiki and skills from the working tree of the engine and the
content overlay. Other sessions leave those checkouts on feature branches or
far behind origin/main. On 2026-10-24 the content checkout was 20 commits
behind and a session read stale notes and missed a documented service.

## Considered options

1. Fold the warning into the byte-stable session directive. Bad, because it
   would break the cache-stable prefix (invariant 11).
2. A separate SessionStart hook that is silent when clean. Good, because the
   clean case adds no context and the stable directive is untouched.

## Decision

We will add a `checkout-guard` SessionStart hook and a `checkout-freshness`
doctor row. Both report branch, commits behind the last-fetched origin/main,
and dirty state for the engine and each resolved overlay. The hook never
touches the network; the doctor fetches first. Branch names and paths are
sanitized and wrapped in nonce-delimited UNTRUSTED markers.

Chosen option: 2.

## Non-goals

Auto-syncing or switching branches: the guard only warns.

## Cross-cutting concerns

- Security: git-controlled strings are sanitized and marked as data.
- Privacy: none.
- Observability: doctor row.

## Consequences

- Good, because stale reads are flagged before use.
- Neutral, because the hook runs a few local git commands per session.

## Confirmation

`engine/setup/tests/nervepack_engine/test_checkout_guard.py`.

## Deviations
