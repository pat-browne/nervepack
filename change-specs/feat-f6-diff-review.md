---
id: 0006
status: accepted
date: 2026-08-15
tier: normal
blast_radius:
  - engine/setup/np-diff-review.py
  - engine/setup/tests/docs/test_diff_review.py
  - .github/workflows/ci.yml
  - change-specs/**
---

# 0006: multi-lens adversarial diff review (F6)

## Context and problem statement

Real test execution already gates merge — the Strong half of criterion 04.
Adversarial review exists only as a convention in
`skills/np-core-dispatch/SKILL.md`, requiring orchestrator activation; it is
never automatic. The Haiku evaluator judges sessions post-hoc, never diffs.

## Considered options

1. **A CI job running four distinct-lens Haiku reviews, posting one
   GitHub PR review with `event: COMMENT`, never voting or blocking** — Good,
   because it matches the measured evidence exactly (advisory, distinct
   lenses, inline suggestions where possible) and reuses F4's verdict schema
   and F5's GitHub-API plumbing. Bad, because it needs a Claude Code OAuth
   token as a GitHub Actions secret that does not exist in this repo yet — a
   real, external dependency this PR cannot resolve on its own.
2. **A marketplace GitHub Action (e.g. an off-the-shelf AI review bot)** —
   Good, zero code. Bad, cannot express the four required distinct lenses,
   cannot be given this repo's own change-spec as context, and is a
   third-party trust dependency this codebase's stdlib-only policy already
   avoids. Rejected.
3. **A single combined prompt asking for all four perspectives at once** —
   Good, one model call instead of four, cheaper. Bad, this is exactly what
   the acceptance criteria and the cited evidence argue against: "distinct
   lens per reviewer, rather than N runs of one prompt" — a single combined
   prompt is closer to one undirected pass than four directed ones, and
   perspective-based review's measured 35% defect-detection gain comes from
   the DIRECTING, not merely from asking broadly. Rejected.

## Decision

We will add `np-diff-review.py`: four Haiku calls (correctness, security,
operability, maintainer-six-months-from-now), each with the project's
AGENTS.md excerpt and this change's own spec as context, findings deduped
only on exact collision (never consensus-filtered), posted as one PR review
with a hardcoded `event: "COMMENT"`, plus an F4-shaped verdict.

Chosen option 1, because it is the only one that can express distinct lenses
with real project context, and the credential dependency is external
infrastructure, not a reason to build something weaker.

## Non-goals

- **Provisioning the `CLAUDE_CODE_OAUTH_TOKEN` GitHub Actions secret.** A
  decision the repo owner makes deliberately (a real Anthropic credential
  exposed to a public repo's CI is security-relevant), not something this PR
  does unilaterally. The user was asked directly and chose to ship the
  mechanism now, add the secret later — see this repo's own AGENTS.md
  "Explicit permission required" boundary for exactly this class of action.
- **True semantic aggregation across lenses** (e.g. weighting a finding two
  lenses independently raised). Findings are deduped only on exact (file,
  line, comment) collision — a light heuristic, not the kind of multi-vote
  consensus adversarial-verify uses for a different purpose (confirming a
  suspected bug). Each lens is meant to catch different things; over-merging
  would suppress genuinely lens-specific findings.
- **Rewriting `np_evaluator.py`'s session judge to also score diffs.** "Point
  the existing evaluator at diffs" is satisfied by this feature existing at
  all — before it, nothing evaluated diffs; the acceptance criterion does not
  require literally reusing the SessionEnd hook's own function, which asks a
  different question (did nervepack help this session) than this one (are
  there defects in this diff).
- **Full GitHub Actions pagination for `pulls/{pr}/files`.** `per_page=100`
  in one call; a PR with over 100 changed files would miss some. Reasonable
  scope cut for this repo's actual PR sizes.

## Cross-cutting concerns

- **Security:** `GITHUB_TOKEN` read from the environment only. `event` is a
  fixed literal in `post_review()`, not a parameter — this is what makes
  "never approves, never requests changes, never blocks" true at the API
  level, not just by convention. `github.head_ref` passed via `env:`, never
  interpolated directly, matching #248's established fix.
- **Privacy:** the diff and AGENTS.md excerpt sent to the model are already
  public (the PR itself, the public engine repo). No new PII surface.
- **Observability:** emits an F4-shaped verdict, picked up automatically by
  the existing `gate-verdicts-summary` job (added to its `needs:` list) —
  no second aggregation mechanism.

**The credential gap is itself a cross-cutting concern, not an oversight.**
Today, in this repo's CI, `model_available()` returns false (no `claude` CLI
installed) and the job logs a skip, writes a SKIPPED verdict, and exits 0 —
verified by running the actual job in CI on this PR (see Confirmation). It
becomes active only once `CLAUDE_CODE_OAUTH_TOKEN` is added as a repo secret
and the workflow installs the `claude` CLI — neither done here.

## Consequences

- Good, because criterion 04's automated-gate gap now has a real, tested
  mechanism, activated by adding one secret rather than by more code.
- Good, because the mechanism is provably advisory at the API level
  (`event` is not a variable), not just documented as advisory.
- Bad, because until the secret is added, this job does nothing but log a
  skip on every PR — an accepted, temporary state, not hidden.
- Neutral, because the four-lens design costs four model calls per PR
  instead of one; justified by the cited 35%/43.67% figures, not assumed.

## Confirmation

`engine/setup/tests/docs/test_diff_review.py` (25 tests): model-availability
detection (mirroring `np_evaluator.py`'s own established check), lenient
JSON parsing via the shared `np-json-extract.py` tool (bare JSON, prose- and
fence-wrapped JSON, malformed input), dedup behavior (collapses exact
duplicates, keeps distinct same-line findings), diff-position parsing from a
real unified-diff hunk format, inline-vs-unplaced comment routing, verdict
shape, `post_review`'s hardcoded `event: COMMENT`, and one full happy-path
integration test with a fake model and fake GitHub API proving all four
lenses' identical findings dedup to one posted inline comment. Workflow YAML
validated to parse and list all 9 jobs. `np-spec-guard.py` dogfooded against
this branch's own diff before push.

CI itself is the confirmation that the fail-open path works for real: this
PR's own `diff-review` job runs with no credential configured, so a green,
skipped run on this very PR is the evidence the fail-open path behaves
correctly in the environment that matters.

## Deviations

None. The change stayed within the declared blast radius.
