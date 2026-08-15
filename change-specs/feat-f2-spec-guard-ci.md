---
id: 0002
status: accepted
date: 2026-08-14
tier: normal
blast_radius:
  - .github/workflows/ci.yml
  - engine/setup/np-spec-guard.py
  - engine/setup/np_frontmatter.py
  - engine/setup/tests/docs/test_spec_guard.py
  - engine/setup/tests/skills/test_np_frontmatter.py
  - change-specs/**
---

# 0002: spec-guard CI job

## Context and problem statement

`change-specs/` (#247/0001) added the artifact format but nothing reads it.
Without a gate it is a convention, and this repo's conventions have already
failed twice as advisory memory (trunk-freshness and superpowers-first, both
2026-08-12). Criterion 01 stays Partial until something checks a PR's diff
against its spec.

## Considered options

1. **A stdlib Python script, run as a CI job, `continue-on-error: true` until
   promoted to the required-checks ruleset** — Good, because it reuses the
   exact advisory-then-required idiom this workflow already has
   (`dashboard-e2e`), needs no new mechanism. Bad, because promotion is a
   ruleset-config change outside this diff — tracked, not forgotten. Neutral,
   because "advisory" here just means "not required", not a second code path.
2. **A GitHub Action from the marketplace** — Good, because zero code to
   write. Bad, because it can't know this repo's spec schema or the
   change-specs/ location, and adds a third-party trust dependency this
   codebase's language policy explicitly avoids (stdlib-only, no external
   deps). Rejected.
3. **Enforce only locally, via a PreToolUse hook, skip CI entirely** — Good,
   because it catches drift earlier. Bad, because that is #249's job, not
   this one, and a hook can be bypassed or simply not fire (a non-Claude-Code
   tool, a manual edit); CI is the backstop regardless of how the diff was
   produced. Rejected as a replacement, kept as a complement (see #249).

## Decision

We will add `np-spec-guard.py` (stdlib-only Python, matching the language
policy) plus a `spec-guard` CI job using the existing
`continue-on-error: true` idiom.

Chosen option: "a stdlib script, advisory via the existing idiom", because it
reuses proven mechanism rather than inventing a second one, and keeps the
promotion decision (advisory → required) as a separate, deliberate step in the
ruleset rather than something this diff decides unilaterally.

## Non-goals

- **Implementing #253's tier registry.** `is_exempt()` uses a path heuristic
  (doc/test-only) until `engine/setup/risk-tiers.json` exists; the function
  checks for that file and has a documented no-op hook to prefer it once
  #253 defines its schema, rather than guessing at one now.
- **Promoting this to a required check in this PR.** That is a ruleset
  change, made after a watch period, per the acceptance criteria in #248.
- **Enforcing blast_radius locally at edit time.** That is #249.

## Cross-cutting concerns

- **Security:** `github.head_ref` and `github.base_ref` are PR-author-
  controlled strings. Passed via `env:` and referenced as shell variables
  (`"$HEAD_REF"`), never interpolated as `${{ }}` directly into the `run:`
  script — caught by this repo's own security-guidance hook on first draft,
  fixed before commit. No other untrusted input reaches a shell command; the
  spec file itself is read as plain text, never executed.
- **Privacy:** no personal data touches this change. `change-specs/*.md`
  files are public by design (see #247/0001's own Confirmation).
- **Observability:** none yet — #250/#251 add structured verdicts and a
  ledger. This job's failure output is the only record for now, visible on
  the PR checks tab.

## Consequences

- Good, because criterion 01's advisory directive now has a real check behind
  it, even before promotion to required.
- Good, because the failure message lists exactly which frontmatter fields
  are missing, per the acceptance criteria — a gate that doesn't say what
  would satisfy it gets bypassed.
- Bad, because the doc/test-only exemption heuristic is a stand-in for #253
  and will need revisiting once that lands (`is_exempt()` docstring says so
  explicitly).
- Neutral, because until this is added to the required-checks ruleset, it
  changes nothing about what can merge — it only makes the gap visible.

## Confirmation

`engine/setup/tests/docs/test_spec_guard.py` (20 tests: pure-helper unit
tests plus 6 CLI end-to-end tests against fixture git repos covering the
happy path, missing spec, blast-radius violation, doc-only exemption,
`[NEEDS CLARIFICATION]` marker, and the non-PR-event no-op) plus 6 new tests
in `test_np_frontmatter.py` for `list_field`. `bash
engine/setup/tests/run-all.sh` green locally before push; CI green on
GitHub's runner before merge.

## Deviations

None — the change stayed within the declared blast radius. One correction
worth recording: the first push of this PR failed its own advisory
`spec-guard` job. Root cause was in the checker, not this spec — the
NEEDS_CLARIFICATION detector was a bare substring search, so this
Confirmation section's own backtick-quoted mention of the marker (describing
the convention, not leaving one open) tripped it. Fixed with a
backtick-boundary regex (`(?<!`)\[NEEDS CLARIFICATION\](?!`)`), covered by a
new test, verified by dogfooding the fixed script against this branch's own
diff before pushing again. Caught by using the mechanism on itself before
merge — the intended effect of #247/#248 landing together.
