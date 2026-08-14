# AI-native compliance — implementation plan

**Tracking issue:** [#258](https://github.com/pat-browne/nervepack/issues/258)
**Date:** 2026-08-14
**Tier:** normal (individual features re-tier; #249, #253, #255 and #257 are high)
**Status:** proposed

---

## Context

An AI-native workflow assessment graded nervepack against seven criteria and
returned **3 Strong · 3 Partial · 1 Weak**. Its finding: the back-end learning
loop (capture → distill → enforce → graduate) is production-grade and
CI-enforced, while the front-end change authoring has no formal gating.

Verified against HEAD `d5eeb67`. A search across markdown, shell, Python and
JSON finds no `risk.?tier`, `auto.?merge`, `high.?risk`, `low.?risk`,
`mandatory human`, or branch-protection/ruleset files. The two adjacent
mechanisms are not this: `auto_safe` in `np_evaluator.py` gates which
*evaluator suggestions* may auto-implement, and `weekly-compact` auto-merges
duplicate *skills* at Jaccard ≥ 0.85. Both are housekeeping.

## Decision

We will close the four gap criteria in dependency order, treating the
**per-change spec artifact as the keystone**, because criteria 05 and 06 both
consume it. We will keep every LLM-driven check advisory and put the blocking
role on deterministic gates.

## Non-goals

These could reasonably be goals and deliberately are not:

- **Simulating a second reviewer.** Self-approval satisfies no control and
  produces misleading audit evidence.
- **Full SBOM, VSA, or CDXA emission.** Their value accrues to downstream
  consumers who do not exist yet. Add when someone asks.
- **A merge queue.** Queues serialize concurrent merges from multiple authors.
  At one author they are latency for nothing.
- **Chasing an OpenSSF Scorecard score.** Code-Review, Branch-Protection tiers
  4–5 and Contributors are unwinnable by construction with one maintainer.
- **Rewriting the superpowers spine.** `np-flow-develop` composes with it; it
  does not replace it.

## Cross-cutting concerns

**Security.** #255 carries the confused-deputy risk directly: gating auto-merge
on `github.actor` is exploitable, because it is the last identity to act on a
PR rather than the author. #249's hook runs before every Write and Edit and must
fail open on its own error, or a parse bug bricks every session.

**Privacy.** All new artifacts land in the public engine repo. Specs and ledger
entries must pass the existing `np-publish-scan.py` PII gate. The wiki topics
backing this work live in the private content overlay; issues carry public
source URLs inline rather than pointing at private paths.

**Observability.** #250 and #251 are the observability work. Every hook logs
each bail and each pass to a named file that `np-core-doctor` can decode.

## Blast radius

```
.github/workflows/**
engine/setup/hooks/**
engine/setup/risk-tiers.json
engine/setup/tests/**
specs/**
docs/superpowers/plans/**
dashboard/data/ledger.jsonl
CODEOWNERS
```

## Confirmation

This plan is satisfied when the assessment re-run returns **7 Strong**, and
concretely when:

- `specs/` contains a spec for every non-standard-tier change merged after
  #248 lands.
- `ledger.jsonl` contains a change-keyed row per merge with a non-null
  `rules_sha`.
- `risk-tiers.json` resolves every path in the tree to exactly one tier, and
  the ratchet test passes.
- A standard-tier change merges without human action; a high-tier change
  cannot.

---

## The waves

Ordering is dependency-driven. Nothing here is preference.

### Wave 1 — the change record

Everything downstream reads this. #251 has nothing to link to and #253 has
nowhere to declare a tier until the spec exists.

| # | Feature | Depends on |
|---|---|---|
| [#247](https://github.com/pat-browne/nervepack/issues/247) | Per-change spec artifact | — |
| [#248](https://github.com/pat-browne/nervepack/issues/248) | `spec-guard` CI job | #247 |
| [#249](https://github.com/pat-browne/nervepack/issues/249) | Spec-drift PreToolUse hook | #247 |

#249 is the item with **no equivalent anywhere in superpowers**.
`executing-plans` stops on a blocker; nothing detects that the work quietly left
the plan. That matters more for agent execution than human: a stale plan makes
an agent confidently execute work that no longer matches reality without
flagging anything.

### Wave 2 — gates that record their reasoning

| # | Feature | Depends on |
|---|---|---|
| [#250](https://github.com/pat-browne/nervepack/issues/250) | Structured gate verdicts | — |
| [#251](https://github.com/pat-browne/nervepack/issues/251) | Change ledger | #247, #250 |
| [#252](https://github.com/pat-browne/nervepack/issues/252) | Auto-invoked adversarial diff review | — (cleaner after #250) |

#252 can start immediately. It is placed here because emitting into #250's
verdict format avoids inventing a second one.

### Wave 3 — risk tiers and auto-merge

Only reachable once a change carries a spec and a machine-readable gate record.

| # | Feature | Depends on |
|---|---|---|
| [#253](https://github.com/pat-browne/nervepack/issues/253) | Risk tier registry | #247 |
| [#254](https://github.com/pat-browne/nervepack/issues/254) | Differential gating by tier | #248, #253 |
| [#255](https://github.com/pat-browne/nervepack/issues/255) | Confidence-gated auto-merge | #249, #250, #252, #253, #254 |

### Wave 4 — hold the two Strong grades

Independent of everything above.

| # | Feature | Note |
|---|---|---|
| [#256](https://github.com/pat-browne/nervepack/issues/256) | Documentation-coupling check | Keys on refactors, not only features |
| [#257](https://github.com/pat-browne/nervepack/issues/257) | Path and host decoupling | Related: #199 |

---

## Findings that shaped the plan

Three results from the standards research changed what gets built.

**1. SLSA v1.2 moved two-party review out of the Source level ladder.** It is
now a separate optional policy attribute, specifically so Source L1–L3 remain
attainable by single-maintainer projects. Anything citing "Source L4 two-person
review" is quoting the retired v0.1 draft. The Weak grade on criterion 05 is not
a compliance failure fixable by adding a reviewer, and does not need to be.

**2. LLM review cannot block.** Measured across 54,713 agent review comments in
341 repositories: 27–45% go unresolved, the largest rejection category is
missing project context at 23.8% rather than wrongness, ~14.3% are outright
incorrect, and LLMs systematically overcorrect toward false alarms. Google ships
its own suggester at a 50% precision target because it is dismissable. GitHub's
Copilot review structurally cannot approve, cannot satisfy CODEOWNERS, and
cannot block. #252 lands non-blocking, with distinct lenses per reviewer —
directed review catches 35% more defects than undirected, and aggregation raises
F1 by up to 43.67%.

**3. Refactoring is the largest source of doc drift.** ICPC 2019, 1.3 billion
AST-level changes across the complete history of 1,500 systems. The changes most
likely to stale documentation are the ones that feel least like they need a doc
update. #256 keys on refactor-shaped diffs, not only feature paths.

## Design rules carried across every feature

- **Gate the delta, not the codebase.** A gate that is unpassable on existing
  code gets disabled, and a disabled gate protects nothing. Sonar's default
  quality gate applies every condition to new code only, and ignores coverage
  and duplication below 20 new lines.
- **Ship advisory, then promote.** GitHub's coverage `evaluate` mode and Azure
  DevOps' `isBlocking` flag both encode this. A badly-calibrated blocking gate
  has no colleague to absorb its false alarms here.
- **Fail closed on a policy violation, fail open on the hook's own error.** Same
  dual-mode posture as `np-pii-filter.py`. A guard that bricks the session gets
  deleted, and then nothing is enforced.
- **Never path-filter a required check at workflow level.** A workflow skipped
  by top-level `paths:` never reports a status, so the check waits forever and
  the PR can never merge. Use a job-level `if:`.
- **Keep strictness with a logged bypass**, never by relaxing the rule. A bypass
  leaves an audit trail; a disabled rule does not.
- **Every hook and job gets a happy-path and a failure-path test** in the
  zero-dependency runner. ARCHITECTURE invariant 6.

## Accepted exceptions

Structurally unattainable with one maintainer. Record them; do not simulate
them.

| Control | Source |
|---|---|
| Two-person review, strongly authenticated | CIS Software Supply Chain Security Guide |
| Segregation of duties (approver ≠ implementer) | ISO/IEC 27001:2022 A.8.32 |
| Independent approval before deployment | SOC 2 CC8.1 |
| Two-party review policy attribute | SLSA v1.2 Source track |
| Code-Review, Branch-Protection T4–T5, Contributors | OpenSSF Scorecard |

Substitutes, ranked by value: make the machine the reviewer; role-directed
self-review; temporal separation (a cooling-off period, not a fixed window);
shift the gate from merge to rollout; keep an immutable audit trail so a bad
change stays detectable even when it was not prevented.

## Standards basis

Six wiki topics with 28 curated reference sources, in the content overlay:
`spec-driven-development`, `ci-quality-gates`, `change-traceability`,
`risk-tiered-change-management`, `docs-as-code`, `host-portability`. Each issue
carries its public source URLs inline.

The workflow that consumes them is the `np-flow-develop` skill, which composes
the superpowers spine (brainstorming → writing-plans → using-git-worktrees →
TDD → requesting-code-review → verification-before-completion →
finishing-a-development-branch) with these criteria at named phases.

## Deviations

None yet. Append here when implementation leaves the declared blast radius.
