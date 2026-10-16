---
id: 0091
status: accepted
date: 2026-10-16
tier: normal
blast_radius:
  - engine/setup/np_implement_suggestion.py
  - engine/setup/np_dashboard_actions.py
  - agents/np-flow-apply-compact-proposal.md
  - agents/np-flow-graduate-candidate.md
  - engine/setup/tests/evaluator/**
  - docs/ARCHITECTURE.md
  - change-specs/fix-kind-jobs-overlay-routing.md
---

# 0091: Run compact and graduate jobs in the content overlay only

## Context and problem statement

The dashboard's compact Apply and graduation Graduate buttons queue kind jobs.
A kind job tried the overlay, then the engine. The engine pass always answered
"wrong repo", so every dead end showed an engine failure. A "keep separate"
Apply did nothing, though AGENTS.md says to record the pair in REJECTED.md.
The graduate prompt pointed at `np-core-graduate`, which moves a skill to a team
overlay and is absent from the overlay worktree. It also named lesson kinds
`strategy|playbook`, while candidates now carry `failure|success`. Kind jobs
landed as a PR, but the overlay has no PR gate.

## Considered options

1. Keep both repos and hide the engine verdict. Bad, because it still spends an
   agent pass on a repo that can never hold the change.
2. Route kind jobs to the overlay only, apply "keep separate" in code, rewrite
   the graduate prompt as lesson-to-skill, land direct on overlay main. Good,
   because each step matches the directory contract.

## Decision

We will run kind jobs in the overlay only (`_kind_repos`). The job bases on the
overlay's origin default branch and pushes there direct. A "keep separate"
compact Apply calls `reject_proposal(action="kept separate")` with no agent
pass. Graduate promotes the lesson into an overlay skill, marks it
`status: promoted`, and dismisses the dashboard candidate.

Chosen option: 2, because the content a kind job edits only exists in the overlay.

## Non-goals

Plain evaluator suggestions keep their target-ordered two-repo routing.

## Cross-cutting concerns

- Security: kind jobs still get no Bash. Untrusted text still sits in the nonce
  data block. A direct overlay push replaces the PR, matching the standing
  overlay policy in AGENTS.md.
- Privacy: no change.
- Observability: a kind job with no overlay fails with a named reason.

## Consequences

- Good, because Apply and Graduate clear their dashboard rows.
- Bad, because an agent edit reaches overlay main without a review PR.
- Neutral, because the local checkout advances only when it sits on the base branch.

## Confirmation

`engine/setup/tests/evaluator/test_implement_kind_overlay.py` and
`test_implement_kinds.py`.

## Deviations
