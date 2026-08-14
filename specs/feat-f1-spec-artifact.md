---
id: 0001
status: accepted
date: 2026-08-14
tier: normal
blast_radius:
  - specs/**
  - AGENTS.md
---

# 0001: Per-change spec artifact (specs/&lt;branch-slug&gt;.md)

## Context and problem statement

The AI-native workflow assessment graded this repo Partial on spec-driven
development: `engine/setup/nervepack-session-directive.md` states process
expectations as an advisory directive injected at session start, with no
reviewable artifact, no approval gate, and no forced re-review when a plan
proves wrong. Criteria 05 (tiered auto-merge) and 06 (traceability) both need
something to attach a tier and a gate record to, and neither has one.

## Considered options

1. **A per-branch spec file in this repo, read by CI** — Good, because CI can
   enforce it and it lives beside the code it governs, the way an ADR lives in
   the repo it documents. Bad, because it adds a file per non-trivial branch.
   Neutral, because it does not replace the existing brainstorming-skill specs
   in the content overlay — the two serve different readers.
2. **Reuse the content overlay's `docs/superpowers/specs/`** — Good, because
   the location already exists. Bad, because CI running on this repo's GitHub
   Actions runners cannot read the private overlay, so nothing could enforce
   it. Rejected on that basis alone.
3. **No artifact, keep the directive advisory** — Good, because zero new
   process. Bad, because this is the status quo the assessment marked
   Partial, and advisory-only process has already failed twice in this repo
   (trunk-freshness and superpowers-first, both 2026-08-12).

## Decision

We will add a `specs/` directory to this repo holding one `TEMPLATE.md`, one
`README.md` documenting the schema and conventions, and one spec file per
governed branch, following the template.

Chosen option: "a per-branch spec file in this repo, read by CI", because it
is the only option CI can actually enforce, and it is a different artifact
from the overlay's design docs rather than a competitor to them.

## Non-goals

- **Replacing `docs/superpowers/specs/` in the content overlay.** That stays
  the home for brainstorming-skill design conversations. This file is a
  short, CI-readable contract, not a design narrative.
- **Requiring a spec for every change.** Standard-tier and spike-path work
  skip it — see `specs/README.md` § "When a spec is not required".
- **Building the enforcement itself.** `spec-guard` (#248) and drift-guard
  (#249) are separate, not-yet-built issues. This change only adds the
  artifact format they will read.

## Cross-cutting concerns

- **Security:** none — this is a documentation and convention change with
  no runtime code.
- **Privacy:** spec files are public, in the public engine repo. No
  personal data belongs in one; the existing `pii-guard` CI job covers this
  file type like any other.
- **Observability:** none yet. #250/#251 add structured verdicts and a
  ledger that will reference specs by path once built.

## Consequences

- Good, because criteria 05 and 06 now have something to attach a tier and a
  gate record to.
- Good, because the immutability and supersession rule gives a durable record
  of rejected alternatives, which a single maintainer has no other way to
  retain.
- Bad, because it is one more file to keep in sync with a branch until
  #249's drift-guard exists to enforce that automatically.
- Neutral, because until #248/#249 land, nothing reads this file — it is
  inert convention, same as the directive it is meant to replace, until the
  next two issues close that gap.

## Confirmation

`specs/feat-f1-spec-artifact.md` (this file) exists, matches the schema in
`specs/README.md`, and is the spec for the branch that added the mechanism —
satisfying #247's "at least one real spec written using it" acceptance
criterion by demonstration rather than assertion.

## Deviations

None. The change stayed within the declared blast radius.
