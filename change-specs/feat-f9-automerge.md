---
id: 0012
status: proposed
date: 2026-08-20
tier: high
blast_radius:
  - engine/setup/automerge.json
  - engine/setup/np_automerge.py
  - engine/setup/np-automerge-gate.py
  - engine/setup/np-ledger-append.py
  - engine/setup/risk-tiers.json
  - engine/setup/tests/docs/test_automerge.py
  - engine/setup/tests/docs/test_ledger_append.py
  - .github/CODEOWNERS
  - .github/workflows/ci.yml
  - .github/branch-protection/**
  - docs/BRANCH-PROTECTION.md
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0012: confidence-gated auto-merge for standard tier (F9)

## Context and problem statement

Code changes never merge without a human here. #254 made every pull request
compute whether it *could* — `tier-policy.json` already carries
`auto_merge_eligible` — and nothing reads it. This is the last piece of
criterion 05 and the one that closes its Weak grade.

The risk is asymmetric and worth stating before the design. A gate that wrongly
blocks costs a bypass. A gate that wrongly merges puts unreviewed code on `main`
under the repository's own authority, and the first person to notice is whoever
hits the bug.

## Decision

We will **enable GitHub's native auto-merge** on eligible pull requests, and
write nothing that performs a merge itself.

That distinction is the whole design. Native auto-merge is a *waiting*
mechanism: GitHub holds the pull request until every required check passes and
every ruleset requirement is met, then merges. It cannot bypass a gate, because
it is on the same side of the gate as a human clicking the button. A workflow
that called the merge API directly would be a *skipping* mechanism wearing a
waiting mechanism's name — it would hold the `pull-requests: write` token that
lets it merge whether the gates passed or not, and its correctness would rest on
our own conditional logic rather than on the ruleset.

So this change ships a **decision**, not a merge. The workflow evaluates
eligibility and, when satisfied, asks GitHub to do the waiting.

## What must hold before auto-merge is enabled

Four conditions decide **eligibility**, evaluated in `np_automerge.py`:

1. `tier-policy.json` says `auto_merge_eligible`. That single field already
   encodes standard tier, every required verdict PASSED, and no open problems.
2. The tier appears in `allowed_tiers`, which is `["standard"]`. Redundant with
   the previous point on purpose: widening it means editing a file classified
   `high`, so the change needs a spec, a rollback plan and the adversarial lens.
3. The pull request's **author** is in `trusted_authors`.
4. The `diff-review` verdict is `PASSED`, meaning the adversarial lens ran.

A fifth condition, `automerge.json`'s `enabled` flag, is kept **separate from
eligibility** rather than folded in as a fifth reason. That separation is what
makes a watch period worth running: with the switch off, the decision record
still says `eligible: true`, which reads as "this change would have merged
itself". Folding the switch into eligibility would produce a record saying only
that auto-merge is disabled, which nobody needs told.

**The policy ships with `enabled: false`.** The decision runs and is recorded on
every pull request from the day this lands, and nothing merges itself until that
one line changes. This is the same shape as every other mechanism here: ship it
reporting, promote it after watching.

## Two things the ruleset already guarantees, so this does not re-implement them

**"Clean adversarial verdict."** `diff-review` never reports FAILED — it is
advisory and always exits 0, by measured evidence and by design. What it does
when it finds something is post review comments, and the ruleset requires
conversation resolution. So a pull request with unresolved findings is
unmergeable natively, and auto-merge simply waits for a human to resolve them.
Rule 5 above therefore checks only that the lens *ran*: SKIPPED means no
adversarial signal exists at all, which is the one state where auto-merging
would be indefensible.

This is also where the advisory reviewer earns a real consequence without
becoming a blocking authority. A finding does not block the change. It demotes
the change from *merges itself* to *a human looks at it*. That is the correct
weight for a signal with 50-to-85-percent precision: a false positive costs one
glance, not a stranded pull request.

**"Verified against the latest base commit."** #254 turned on
`strict_required_status_checks_policy`, so a pull request cannot merge while its
branch is behind `main`. Moving the base makes the pull request out of date, and
it must be updated — which re-runs every check against the new base — before
anything can merge. That is Prow/Tide's published guarantee, obtained from the
ruleset rather than from code.

**Deviation from the issue's wording.** #255 asks that auto-merge be "disabled
automatically when the base branch changes". We achieve the intent by a
different mechanism: auto-merge stays enabled and becomes unable to fire until
the branch is re-verified. Nothing merges on checks computed against a stale
base either way, and leaving it enabled avoids a second failure mode where a
routine base move silently drops the request on the floor.

## Security

These are not incidental. The documented Dependabot pwn-request applies directly
to any workflow that can merge.

**Never `github.actor`.** That context is *the last identity to act on the pull
request*, not its author. An attacker who can cause any bot activity on a pull
request they control flips it and inherits the privileged path. The decision
reads `github.event.pull_request.user.login`, and `np_automerge.decide` takes
the author as an argument so a test can prove which one is used.

**Never a branch-name prefix as identity.** Branch names are attacker-
influenceable. Nothing here reads one.

**Never `pull_request_target`.** The job runs on `pull_request`, so a fork's
token is read-only and cannot enable auto-merge at all. The fork case fails
closed with no special handling, which is the shape to prefer over a conditional
that has to be correct.

**Explicit workflow-level `permissions:`.** `ci.yml` had none, so every job ran
with the repository default. It now declares `contents: read` at the top, and
the three jobs that need more declare their own.

**Third-party actions.** There are none — every `uses:` in `ci.yml` is a
first-party `actions/*` step. A test asserts that stays true, because the day one
arrives is the day the SHA-pinning rule starts to matter and nobody will
remember it.

**Auto-merge is not the first point of compromise.** A malicious dependency's
install scripts execute in CI before any human sees the pull request. Whatever
auto-merge does or does not do, the runner has already run the code. This is
recorded so that auto-merge is not mistaken for the boundary it is not.

## The ledger line cannot come from CI

`np-ledger-append.py` says why already: `dashboard/data/` lives in the private
content overlay, and a public-repo Actions job has no write access to it and
must not be given any. A human running that command has been the mechanism until
now, and an auto-merged pull request has no human in the loop.

So `np-ledger-append.py` gains `--backfill`, which lists recently merged pull
requests and appends every one the ledger is missing. It runs locally, like
everything else that writes to the overlay. The F4 verdict for the auto-merge
decision *is* written from CI, because verdicts are artifacts in the engine repo.

This is a real gap in the acceptance criteria as written, and closing it by
giving CI a cross-repo token would trade a bookkeeping delay for a credential in
the wrong place.

## Considered options

1. **Enable native auto-merge from a decision job** (chosen) — Good, because the
   waiting guarantee comes from GitHub rather than from our conditional. Good,
   because a fork PR fails closed without a code path. Bad, because it needs
   `allow_auto_merge` on at the repository level, which is a setting no file in
   this repo can hold.
2. **A workflow that calls the merge API when it judges the PR ready** — Good,
   because it needs no repository setting and the logic is all visible in one
   place. Bad, and disqualifying, because that job holds a token that can merge
   regardless of gate state. The whole safety property would rest on our `if:`
   being right, forever, including on the day someone edits it.
3. **Merge queue** — rejected in #254 and still rejected. Queues serialize
   concurrent merges from several authors; at one author they are latency for
   nothing.

## Non-goals

- **Normal and high tier never auto-merge**, and no configuration in this change
  makes them. `allowed_tiers` exists to make widening it an audited edit, not to
  invite one.
- **No batching.** One pull request at a time.
- **No auto-approval.** Nothing here approves anything; required approvals stay
  at zero.

## Cross-cutting concerns

**Security.** Covered above at length; it is the substance of this change.

**Privacy.** The decision record names a GitHub login, which is already public on
every pull request.

**Observability.** The decision writes `gate-verdict-auto-merge.json` whether it
enables auto-merge or declines, and the reasons are listed in it. A decision
that only records itself when it fires cannot be audited for the case that
matters, which is the one where it fired and should not have.

## Consequences

**Good.** Standard-tier changes — docs, wiki, skill references, test-only work —
stop waiting on a human who has nothing to add. Criterion 05 reaches Strong.

**Bad.** `tier-gate` is promoted to a required check in this change, which means
a high-tier pull request whose `diff-review` SKIPPED cannot merge without an
admin bypass. On a fork, `diff-review` always skips, so a fork pull request
touching a hook is blocked pending maintainer action. That is defensible for
high-risk paths and it is still a real narrowing, recorded here rather than
discovered later.

**Neutral.** `allow_auto_merge` goes on at the repository level. It does nothing
by itself; without an explicit enable call no pull request behaves differently.

## Confirmation

- `test_automerge.py` asserts each of the five conditions independently blocks,
  that the author is read from the pull request author rather than the actor,
  that an unknown tier never qualifies, and that a disabled policy overrides
  everything else.
- `test_automerge.py` also asserts every `uses:` in `ci.yml` is a first-party
  `actions/*` step, and that `ci.yml` declares workflow-level `permissions:`.
- `test_ledger_append.py` covers `--backfill` skipping pull requests already in
  the ledger and appending the ones missing.
- `engine/setup/automerge.json`, `np_automerge.py` and `np-automerge-gate.py`
  resolve to `high` through `np_risk_tiers.tier_for`.

## Rollback

Ordered loosest first. Each step stands alone.

**Stop auto-merging, immediately, with no deploy.** Set `"enabled": false` in
`engine/setup/automerge.json` and merge that one-line change. It is the first
condition evaluated, so nothing downstream runs.

**Stop it without merging anything**, if the repository itself is the problem:

```bash
gh api -X PATCH repos/pat-browne/nervepack -F allow_auto_merge=false
```

`-F`, not `-f`: `-f` sends the value as the string `"false"`, which is not a JSON
`false`. Getting this wrong disables nothing while looking like it did.

Native auto-merge cannot be enabled on any pull request while that is off, and
already-enabled requests stop firing.

**Cancel a specific pending auto-merge:**

```bash
gh pr merge <N> --disable-auto --repo pat-browne/nervepack
```

**Demote `tier-gate` back to advisory.** Restore `continue-on-error: true` on
the job, put `advisory` back in its `name:`, and apply the ruleset with that
context removed:

```bash
id=$(gh api repos/pat-browne/nervepack/rulesets --jq '.[] | select(.name=="main") | .id')
gh api -X PUT repos/pat-browne/nervepack/rulesets/$id \
  --input .github/branch-protection/ruleset-main.json
gh api repos/pat-browne/nervepack/rulesets/$id \
  --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
```

Read the contexts back. A required context that no job produces waits forever,
and that failure looks identical to a check that has not started yet.

**Remove the decision entirely.** Delete the `auto-merge` job from `ci.yml`. The
three modules are inert if unreferenced: nothing imports them except that job
and their tests.
