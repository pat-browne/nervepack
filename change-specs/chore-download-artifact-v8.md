---
id: 0019
status: proposed
date: 2026-08-25
tier: high
blast_radius:
  - .github/workflows/ci.yml
  - change-specs/chore-download-artifact-v8.md
---

# 0019: actions/download-artifact v7 to v8

## Context and problem statement

Dependabot opened #280 to bump `actions/download-artifact`. It cannot merge, for
two separate reasons, and both are worth stating because only one is its fault.

**It is incomplete.** #280 was raised against an older `main` and patches two of
the three `download-artifact` uses. Merging it would leave the third at v7 —
mixed majors of the same action inside one workflow, which is a worse state than
either version alone.

**It cannot satisfy `spec-guard`.** `.github/workflows/**` is high tier, so the
gate demands `change-specs/dependabot-github_actions-actions-download-artifact-8.md`.
A bot cannot write a change spec. That is a structural consequence of the gates
this epic added, it blocks every future dependency PR, and it is filed separately
— this change does not attempt to fix it.

## Decision

We will bump all three `download-artifact` uses to v8 and leave
`upload-artifact` at v7.

**`upload-artifact` has no v8.** The v8 release notes describe support for
"direct uploads in `actions/upload-artifact`", which reads as a paired change,
so the first question was whether v8 download can read a v7 upload. It has to:
v8 is published and its counterpart is not, so a v7 producer is the only producer
that exists.

## The two breaking changes, against what this repo does

**Non-zipped downloads are no longer unzipped.** v8 checks `Content-Type` and
skips decompression for anything that is not a zip. Every artifact here is
produced by `upload-artifact@v7`, which zips, so this path is not reached.

**A hash mismatch now errors instead of warning.** This is a stricter check on a
condition that should never occur, and erroring is the correct response to a
corrupted artifact. Left at the default deliberately: the artifacts being
downloaded are the gate verdicts and the tier policy, which decide whether a
change may merge. Silently accepting a corrupted one is the failure this whole
epic exists to prevent.

## Considered options

1. **Bump all three, keep upload at v7** (chosen) — Good, because it is the
   complete version of what #280 intended and leaves no mixed state. Bad,
   because it pairs a v8 consumer with a v7 producer, which is only safe as long
   as v8 keeps reading v7 artifacts.
2. **Merge #280 as-is** — rejected: it leaves one use at v7.
3. **Stay on v7** — defensible, and rejected because v7 warns on a hash mismatch
   where v8 errors, and the artifacts in question gate merges.

## Non-goals

- **Fixing the dependabot blocker.** Filed separately. Writing this spec by hand
  is not a fix, it is one maintainer absorbing the cost once.
- **Pinning actions to commit SHAs.** #255 established these are all first-party
  `actions/*` and a test asserts it; SHA pinning is for third-party actions and
  none exist here.

## Cross-cutting concerns

**Security.** A stricter digest check on artifacts that decide merge eligibility
is the direction to move in. `download-artifact` runs in jobs holding
`pull-requests: write` and, in one case, `contents: write`.

**Observability.** If v8 cannot read a v7 artifact, `gate-verdicts-summary` posts
a comment with missing gates and `tier-gate` reports absent verdicts as problems
rather than passes. The failure is loud by construction, which is why this is
verifiable on the pull request itself.

## Consequences

**Good.** All three uses agree. A corrupted verdict artifact now fails instead of
being consumed.

**Bad.** A v8-consumer/v7-producer pairing is a combination the upstream project
will support only until it does not.

## Confirmation

The pull request is its own test. `tier-gate` and `gate-verdicts-summary` both
download every `gate-verdict-*` artifact; if v8 could not read them, `tier-gate`
would report absent verdicts and the summary comment would be missing rows.
A green `tier-gate` with a full verdict table is the evidence.

## Rollback

Revert. v7 is still published and the artifacts are unchanged in format, so a
revert needs no coordination with anything already uploaded.
