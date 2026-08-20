---
id: 0009
status: proposed
date: 2026-08-19
tier: high
blast_radius:
  - engine/setup/risk-tiers.json
  - engine/setup/np_risk_tiers.py
  - engine/setup/np-spec-guard.py
  - engine/setup/tests/**
  - docs/RISK-TIERS.md
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0009: risk tier registry (F7)

## Context and problem statement

Change specs already carry a `tier:` field, and `spec-guard` already validates
it against `standard|normal|high`. Nothing checks whether the declared tier is
*true*. A change touching `engine/nervepack_engine/hooks/` can declare
`tier: standard` today and pass every gate.

`spec-guard` also decides which diffs need a spec at all, using a hardcoded
`EXEMPT_GLOBS` heuristic it documents as a placeholder:

```python
# Exempt today: doc-only and test-only diffs (a path heuristic). Once
# engine/setup/risk-tiers.json exists (#253) its standard-tier globs should take
# precedence over this heuristic - not implemented yet, since that issue hasn't
# defined the schema.
```

So the tier exists as a word in a file and nowhere as a decision. F8 (#254)
cannot vary gates by tier and F9 (#255) cannot gate auto-merge on it until
something can answer "what tier is this diff, really".

## Considered options

1. **An ordered rule list, last match wins, in `engine/setup/risk-tiers.json`** —
   Good, because ordering is explicit in the data, reviewable in a diff, and
   mirrors CODEOWNERS, which solved this exact precedence problem. Good, because
   a reader resolves a path by scanning down and taking the last hit, with no
   specificity algorithm to reason about. Bad, because last-match-wins is the
   opposite of most people's intuition and must be documented loudly or it will
   be mis-edited.

2. **A tier-keyed object** (`{"high": [globs], "normal": [...]}`), the shape the
   issue sketches — Good, because it reads naturally and groups related globs.
   Bad, and disqualifying: JSON object key order is not semantically guaranteed,
   so "last match wins" cannot be expressed at all. Precedence would have to
   come from a hardcoded tier ranking instead, which means a glob's position in
   the file stops mattering and the CODEOWNERS parallel is lost. Rejected on
   mechanism, not taste.

3. **Most-specific-glob-wins** — Good, because it needs no ordering discipline.
   Bad, because "specific" has to be defined (segment count? wildcard count?
   literal-character count?), every definition has surprising cases, and
   CODEOWNERS explicitly chose ordering over specificity to avoid exactly this.
   Rejected.

## Decision

We will add `engine/setup/risk-tiers.json`: a schema-versioned, **ordered** list
of `{glob, tier}` rules with a `default` tier, and `engine/setup/np_risk_tiers.py`
to resolve it. **Last match wins**, so high-risk globs go last.

`np-spec-guard.py` will consume it in two places:

- **Exemption.** The `EXEMPT_GLOBS` heuristic is replaced by the registry: a diff
  is exempt when every touched path resolves to `standard`. This is what the
  code's own comment asks for.
- **Escalation.** A spec declaring a tier *lower* than its touched paths require
  fails, naming the path that forced the higher tier. Declaring **higher** than
  required always passes: the ratchet only turns one way.

**The registry classifies itself `high`.** Without that, the policy governing how
much scrutiny every change receives could be rewritten in a standard-tier diff
that needs no spec and no review — a privilege escalation with the tiering
mechanism as the vector. `risk-tiers.json`, `np_risk_tiers.py`, and
`np-spec-guard.py` are all high-tier rules in the shipped file.

Chosen option: "an ordered rule list, last match wins", because it is the only
option of the three that can express precedence in the data rather than in code,
and because CODEOWNERS is prior art a reader may already know.

## Non-goals

**Enforcing the one-way ratchet mechanically.** CI sees one diff, not a task's
history, so it cannot know a change was called `standard` an hour ago. The
escalation check enforces the ratchet's *outcome* — a too-low declaration fails.
The rest is a process rule in `np-flow-develop`, and this spec will say so rather
than imply CI covers it.

**Layer-extensible tiers.** A content overlay or team layer contributing its own
globs is a real want and is tracked by #36. Adding a merge order now, with one
layer and no caller, is scaffolding.

**Differential gating and auto-merge.** #254 varies the gate set by tier and #255
gates auto-merge on it. This issue only answers "what tier is this diff".

**A published taxonomy.** There is not one. CIS says "extra sensitive code or
configuration" without defining it, Google's *Building Secure and Reliable
Systems* says "safety implications", SLSA says "security-relevant properties".
Every organization invents its own list. That sentence stays in the shipped file,
not only in this spec.

## Cross-cutting concerns

- **Security:** this file decides how much scrutiny a change receives, so a
  downgrade is a privilege escalation. Two mitigations, both in the shipped
  rules: the registry classifies itself and its consumers `high`, and the
  escalation check makes a false low declaration a CI failure rather than a
  silent pass. Globs are matched with `fnmatch`, never executed, same posture as
  `np_change_spec`.
- **Privacy:** none. Path globs only, no file contents, no telemetry.
- **Observability:** `spec-guard`'s failure output names the resolved tier, the
  required tier, and the specific path that forced it. A tier failure that does
  not say *which file* caused it is unactionable.

## Consequences

- Good, because the `tier:` field stops being decorative, and F8 and F9 become
  buildable.
- Good, because `spec-guard`'s placeholder heuristic is replaced by the thing its
  own comment asks for, in one place both it and future callers read.
- Bad, because last-match-wins will be mis-edited by someone appending a
  standard-tier glob at the bottom and silently downgrading everything it
  matches. Mitigated by ordering comments in the file, the companion doc, and a
  test asserting the self-classification survives.
- Bad, because a previously-passing branch that under-declared its tier now
  fails. That is the feature, and it may bite an in-flight branch.
- Neutral, because no gate changes strength yet. A high-tier change is gated
  exactly as a normal one is until #254.

## Confirmation

- `engine/setup/tests/docs/test_risk_tiers.py`: last-match-wins precedence
  (a later rule overrides an earlier match on the same path), the `default` for
  an unmatched path, and the ratchet direction (declaring higher passes,
  declaring lower fails).
- **Self-classification test**: `risk-tiers.json`, `np_risk_tiers.py`, and
  `np-spec-guard.py` each resolve to `high`. This fails if someone appends a
  broad standard glob at the bottom, which is the file's main foreseeable
  mis-edit.
- A test asserting the "synthesis, not a citation" sentence is present in the
  shipped JSON, so honesty about the taxonomy cannot be quietly dropped.
- `np-spec-guard.py --base main --head HEAD` on this branch resolves `high` from
  its own touched paths and agrees with this spec's declared `tier: high`.

## Rollback

1. Revert the commit. `spec-guard` returns to the `EXEMPT_GLOBS` heuristic and
   stops checking declared tiers; nothing else reads the registry yet, so there
   is no second consumer to unwind.
2. Narrower, no revert: edit `risk-tiers.json` so every rule is `standard`. The
   escalation check then passes everything. Recorded here because it is the
   obvious panic move, and it should be a deliberate, reviewable commit to a
   high-tier file rather than a quiet local edit.

## Deviations

<Append here when implementation leaves the declared blast radius. Each entry:
date, what was touched outside blast_radius, and the one-line reason. Never
delete a prior entry.>
