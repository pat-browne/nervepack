---
id: 0033
status: proposed
date: 2026-09-10
tier: high
blast_radius:
  - engine/setup/np_dependency_bump.py
  - engine/setup/np-spec-guard.py
  - engine/setup/np-tier-gate.py
  - engine/setup/np_tier_policy.py
  - engine/setup/risk-tiers.json
  - .github/CODEOWNERS
  - engine/setup/tests/**
  - .github/workflows/ci.yml
  - change-specs/**
---

# 0033: A dependency version bump is exempt from the spec requirement, never from review

## Context and problem statement

`spec-guard` became required in #254. `.github/workflows/**` is `high` tier, so
any diff touching it needs `change-specs/<branch-slug>.md`. Dependabot's branch
is `dependabot/github_actions/actions/download-artifact-8`, so the gate demands
a file **a bot cannot write**.

`tier-gate` blocks the same PR independently. `high` sets `rollback_required`,
and `_rollback_problems(None)` returns "tier requires a rollback plan, but no
change spec was found". Fixing only `spec-guard` would leave the PR stuck, so
this is one change across two gates.

Every GitHub Actions dependency update is permanently blocked. #305 superseded
#280 by hand, with a maintainer writing the spec. That is one person absorbing
the cost once, and it does not scale.

A change spec records a design decision. A version bump has no design to
record. It still deserves review, because `.github/workflows/**` is exactly
where repo secrets are in scope and a compromised action is a real
supply-chain vector.

## Considered options

1. **Exempt an allowlisted bot author whose diff is confined to version bumps**
   — Good, because the spec requirement is the only thing a bot cannot satisfy,
   and every other gate still runs. Good, because the diff check, not the
   author, carries the security. Bad, because it adds a second exemption path
   through two gates that must stay in step.
2. **Exempt bot authors outright** — Bad. `.github/workflows/**` is high tier
   precisely because it is where secrets are in scope, and this exempts the
   case most worth reviewing. It is also the confused-deputy shape #255 warns
   about: a collaborator can push to a dependabot branch while
   `pull_request.user.login` stays `dependabot[bot]`.
3. **Downgrade `.github/workflows/**` to standard** — Bad. It weakens the gate
   for genuine workflow changes to solve a problem with bot-authored ones.
4. **Use the ruleset bypass each time** — Bad. #254 designed the logged bypass
   for the rare case. A bypass that fires on routine work stops being an audit
   signal, which is the argument that turned off
   `require_extra_approval_for_unattributed_changes` on #291.

## Decision

We will add `engine/setup/np_dependency_bump.py`, one predicate imported by
both `np-spec-guard.py` and `np-tier-gate.py`. A diff is exempt from the
**spec** requirement, and from the spec-derived **rollback** requirement, only
when BOTH hold:

1. **The PR author is an allowlisted bot.** Read from
   `github.event.pull_request.user.login`, passed explicitly as `--author`.
   Never `github.actor`, which is the last identity to act on the PR rather
   than its author.
2. **Every changed line is a dependency version bump.** Each changed file is on
   a manifest allowlist, added and removed line counts match per file, and each
   removed/added pair is byte-identical once version tokens are normalized
   away.

Chosen option: "exempt an allowlisted bot author whose diff is confined to
version bumps", because condition 2 is a real check on content rather than
trust in an identity.

Neither condition is sufficient alone, and that is the point. Condition 1 alone
is the confused deputy. Condition 2 alone lets any human skip a spec by shaping
a change to look like a bump.

## Non-goals

Exempting anything from **review**. The five deterministic gates, the
adversarial lens, and `tier-gate`'s requirement that the lens actually RAN all
still apply. `auto_merge_eligible` stays `False` for `high`, so a human still
merges.

Judging whether the bumped version is safe. A malicious tag is a supply-chain
risk that exists with or without this change, and a change spec would not have
caught it either.

Widening the allowlist beyond this repo's actual dependabot surface. Today that
is `.github/workflows/*.yml` and the e2e `package.json`/`package-lock.json`.

## Cross-cutting concerns

- **Security:** the exemption is gated on diff content, not author trust. A
  collaborator pushing anything else onto a dependabot branch changes the diff,
  so condition 2 fails and the spec is required again. The author string is
  GitHub-computed and never PR-author-controlled, and is passed through `env:`
  rather than interpolated into a `run:` script.
- **Privacy:** none.
- **Observability:** both gates print which condition granted the exemption and
  which file forced it, so an exempt run is never silent about why.

## Consequences

- Good, because GitHub Actions updates stop being permanently blocked.
- Good, because the reviewed surface does not shrink.
- Bad, because two gates now share an exemption predicate that must stay in
  step. One module imported by both, with a test asserting they agree, is the
  mitigation.
- Neutral, because a dependabot PR that touches anything else is blocked
  exactly as it is today. The change fails closed.

## Confirmation

Tests in `engine/setup/tests/docs/`:

- the real #280 diff (three `actions/download-artifact@v7` to `@v8` lines) is
  exempt for `dependabot[bot]`
- the same diff is NOT exempt for a human author
- a bump-shaped diff plus one unrelated line is NOT exempt, driving the
  confused-deputy case
- a non-bump change to an allowlisted file is NOT exempt
- a bump to a file off the allowlist is NOT exempt
- `spec-guard` and `tier-gate` return the same exemption answer for the same
  input, so the two cannot drift
- the predicate matches something, so a version-token regex that degrades to
  matching nothing fails rather than reading as a clean refusal
  ([[np-kb-test-quality]] §15)

## Rollback

Revert the commit. Both gates return to requiring a change spec for every
non-exempt diff, which is today's behaviour: dependabot PRs block again, and
nothing that is currently reviewed becomes unreviewed. The change fails closed
in both directions, so a revert needs no data migration and no ruleset edit.

If only the exemption misbehaves and the gates are otherwise wanted, set the
bot allowlist in `np_dependency_bump.py` to empty. Condition 1 then never
holds, and both gates behave exactly as before this change.

## Deviations

