---
id: 0010
status: proposed
date: 2026-08-20
tier: high
blast_radius:
  - engine/setup/np_tier_policy.py
  - engine/setup/np-tier-gate.py
  - engine/setup/np_codeowners.py
  - engine/setup/risk-tiers.json
  - engine/setup/tests/docs/test_tier_policy.py
  - engine/setup/tests/docs/test_tier_gate.py
  - engine/setup/tests/docs/test_codeowners.py
  - .github/CODEOWNERS
  - .github/workflows/ci.yml
  - .github/branch-protection/**
  - docs/RISK-TIERS.md
  - docs/ARCHITECTURE.md
  - docs/BRANCH-PROTECTION.md
  - change-specs/**
  - INDEX.md
---

# 0010: differential gating by tier (F8)

## Context and problem statement

Every substantive change takes the same path today: open a PR, wait for five
deterministic checks, merge by hand. The tier registry (#253) can already tell
you that a diff touching `engine/nervepack_engine/hooks/` is `high` and a diff
touching `README.md` is `standard`, but nothing consumes that answer. Both
changes face the identical gate set, so the registry is a label with no
consequence.

DORA authorizes the tiering directly: "perform ongoing analysis to detect and
flag high-risk changes early so they can be subjected to additional scrutiny."
The word doing the work is *differential*. Scrutiny that does not vary is not
scrutiny, it is overhead applied evenly.

Two constraints shape the answer.

**GitHub cannot vary required review count by changed path.** Path sensitivity
is expressible only through CODEOWNERS plus "require code owner review", or
through a status check computed inside the repo. GitLab's `[Section]` syntax can
require N approvals per path. GitHub cannot. With one maintainer the CODEOWNERS
route is inert anyway, because required approvals are zero and the only owner is
the author. So the check has to be computed in-repo.

**The adversarial lens is advisory and must stay advisory.** Measured LLM review
precision is 50 to 85 percent, and the largest rejection category is missing
project context rather than wrongness. #252 landed non-blocking for that reason
and nothing here changes it.

## Decision

We will compute a per-PR **tier policy** in CI, from the tier the diff resolves
to, and vary *which gate verdicts must be PASSED* rather than which gates run.

Every PR runs the same jobs. The tier decides which of their verdicts are
load-bearing:

| Tier | Verdicts that must be PASSED | Extra content requirement | Merge authority |
|---|---|---|---|
| standard | the five deterministic gates | none | deterministic gates (auto-merge eligible, #255) |
| normal | the five, plus `spec-guard` | none | human |
| high | the five, plus `spec-guard` | spec has a non-empty `## Rollback`; `diff-review` must have **run** | human, never auto-merge |

"Must have run" is deliberately weaker than "must have passed". Requiring the
adversarial lens to *approve* would make a 50-to-85-percent-precision reviewer a
blocking authority, which the epic's own findings forbid. Requiring it to have
been *applied* is the strongest honest form of "subject high-risk changes to
additional scrutiny": the lens was pointed at the diff and its output is on the
PR, and a human decides what to do with it.

## Considered options

1. **A computed status check reading the other gates' verdicts** (chosen) —
   Good, because F4 already emits a machine-readable verdict per gate, so the
   policy is a pure function over artifacts that already exist, and it composes
   instead of duplicating: tier-gate never re-checks what spec-guard checked, it
   requires spec-guard's verdict. Good, because the same JSON it writes is
   exactly what #255 needs to decide auto-merge. Bad, because it adds a job that
   depends on six others, so it reports last and lengthens the critical path by
   one runner start.
2. **Conditional job execution — skip gates that a tier does not need** —
   Good, because it is cheaper: a docs PR would not start a Windows runner. Bad,
   and disqualifying, because a skipped required check on GitHub is
   indistinguishable from a pending one, so a required check that is conditionally
   skipped **strands the PR forever**. The documented workaround is a
   permanently-passing dummy job per skipped gate, which trades one confusing
   mechanism for two. Cheapness is not worth a merge deadlock.
3. **CODEOWNERS plus "require review from code owners"** — Good, because it is
   native, needs no code, and is the mechanism GitHub actually offers for path
   sensitivity. Bad, and disqualifying today, because required approvals are zero
   and the sole code owner is the author of every PR, so it enforces nothing. It
   is kept as *declaration and routing*, generated from the registry, not as a
   gate.

## Non-goals

- **Auto-merge is not built here.** This change decides and records
  `auto_merge_eligible`; #255 acts on it. Deciding and acting are separated so
  the decision can be watched on real PRs before anything merges itself.
- **tier-gate does not block on this PR.** It ships `continue-on-error: true`
  and stays out of the required set, per this repo's own "ship advisory, then
  promote" rule. Its promotion is #255's first step, not this one's last.
- **No merge queue.** Queues serialize concurrent merges from several authors.
  At one author they are latency for nothing.
- **CODEOWNERS is not translated exactly.** See cross-cutting concerns.

## Cross-cutting concerns

**Security.** The tier registry, the resolver, spec-guard and now the tier
policy modules all classify themselves `high`, so the policy governing scrutiny
cannot be rewritten in a diff that escapes scrutiny. `risk-tiers.json` gains
three self-rules for the files this change adds. Without them, `np_tier_policy.py`
would resolve to `normal` and the thresholds could be lowered by a change needing
no rollback plan and no adversarial lens.

`np-tier-gate.py` reads only artifacts produced inside the same workflow run and
files from the checked-out tree. It holds no credential and posts nothing.

**Privacy.** No new data leaves the runner. The tier policy JSON names repo-
relative paths that are already public in the diff.

**Observability.** The policy artifact is uploaded on every PR whether it passes
or fails, and its verdict joins the existing gate-verdicts PR comment. A gate
that reports only on failure cannot be watched during an advisory period, which
is the entire purpose of an advisory period.

**Translation fidelity.** `risk-tiers.json` globs are `fnmatch`, where `*`
crosses `/`. CODEOWNERS patterns are gitignore-style, where `*` does not. The
generated file is therefore an approximation in both directions: `engine/setup/*install*`
under-matches (it will not reach a nested `install-x.sh`), and `**/*cron*`
over-matches (it also reaches a top-level `cron.py`). This is acceptable only
because the generated file routes review requests and documents intent, while
`np-tier-gate.py` and `np-spec-guard.py` — both reading `fnmatch` directly — do
the enforcing. The header of the generated file says so, and a test asserts the
header says so.

## Consequences

**Good.** The tier registry stops being a label. A `high` change now has three
requirements a `normal` change does not, and they are stated in one place as
data. #255 gets its input as a file rather than as a re-derivation.

**Bad.** The critical path grows by one job that cannot start until six others
finish. On a green PR that is roughly one extra runner start. A gate that reports
last is also the gate most likely to be read after the author has moved on.

**Neutral.** `spec-guard` is promoted from advisory to required in the same
change. It has run on every PR since #248 and has been correct on all of them,
which is the watch period the README asked for. Promotion means dropping its
`continue-on-error` and dropping "advisory" from its display name, so the old
check context disappears; because branch protection is being rewritten as a
ruleset here anyway, no stranded required context is left behind.

**Neutral.** Classic branch protection is replaced by a ruleset. GitHub began
auto-migrating classic rules in August 2026, so this is a migration that was
going to happen either way; doing it deliberately keeps the JSON under version
control instead of accepting whatever the automatic migration produces.

## Confirmation

- `engine/setup/tests/docs/test_tier_policy.py` asserts the tier-to-requirement
  table above, including that `high` requires `diff-review` to have run but not
  to have passed, and that an unknown tier yields no auto-merge.
- `engine/setup/tests/docs/test_tier_gate.py` drives the CLI over fixture
  verdict directories and asserts exit codes and the written policy JSON.
- `engine/setup/tests/docs/test_codeowners.py` asserts the committed
  `.github/CODEOWNERS` is byte-identical to the generator output, that it stays
  under the 3 MB cap, and that its header carries the translation caveat.
- `engine/setup/tests/docs/test_risk_tiers.py` already asserts no standard rule
  follows a high one; the three new self-rules are covered by extending its
  self-classification case.
- The live ruleset is checked in at `.github/branch-protection/ruleset-main.json`
  and the replaced classic configuration at
  `.github/branch-protection/classic-main.backup.json`.

## Rollback

Three independent steps, in the order that restores the loosest state first.

1. **The ruleset.** `gh api -X DELETE repos/pat-browne/nervepack/rulesets/<id>`
   removes it, then
   `gh api -X PUT repos/pat-browne/nervepack/branches/main/protection --input .github/branch-protection/classic-main.backup.json`
   restores exactly the classic protection this change replaced. The backup file
   is the pre-change API response, committed for this purpose.
2. **spec-guard's promotion.** Restore `continue-on-error: true` on the
   `spec-guard` job and remove its context from the ruleset's required checks.
   Independent of step 1 only if the ruleset survives; if step 1 already ran,
   this is a no-op.
3. **tier-gate itself.** Delete the `tier-gate` job and remove it from
   `gate-verdicts-summary`'s `needs`. It is `continue-on-error: true` and holds
   no credential, so leaving it in place while investigating is also safe — it
   cannot block a merge or fail a required check.

The three Python modules are inert if unreferenced: nothing imports them except
the CI job and their tests.

## Deviations

- 2026-08-20 — added `engine/setup/risk-tiers.json` to the blast radius. The
  cross-cutting concerns section above always said this change gives the three
  new modules self-classifying rules, and the glob was simply left out of the
  frontmatter. `spec-guard` caught it on the first local run against the real
  diff, which is the case the gate exists for: prose and frontmatter disagreeing
  about the same change.
