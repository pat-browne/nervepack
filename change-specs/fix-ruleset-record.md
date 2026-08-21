---
id: 0011
status: proposed
date: 2026-08-20
tier: high
blast_radius:
  - engine/setup/risk-tiers.json
  - .github/CODEOWNERS
  - .github/branch-protection/**
  - docs/BRANCH-PROTECTION.md
  - change-specs/**
---

# 0011: make the branch-protection record match reality, and protect it

## Context and problem statement

Applying #254's ruleset surfaced two things that change had no way to know in
advance, because both are only observable against the live API.

**GitHub added a parameter we never declared.** The created ruleset came back
carrying `require_extra_approval_for_unattributed_changes: true`, a server-side
default. It requires one approving review whenever a pull request contains a
commit GitHub cannot attribute to an account. With zero required approvals and
one maintainer, that is a requirement nobody here can satisfy: a single author
cannot approve their own pull request, so any commit authored from an unlinked
email address would leave the change mergeable only by admin bypass. #254's
second acceptance criterion exists specifically to avoid an approval
requirement one maintainer cannot meet.

**The record of the required checks was not itself a protected path.**
`.github/branch-protection/ruleset-main.json` resolved to `normal`. The file
lists which status checks are required, so a change could have rewritten that
list while needing no rollback plan and no adversarial lens — the same
escalation the registry's self-classifying rules exist to prevent, one level
out.

## Decision

We will set the parameter to `false`, commit the value so the file matches the
live ruleset, and classify `.github/branch-protection/**` as `high`.

Turning the parameter off is not the rule-relaxing the bypass policy warns
against. A relaxation escapes a requirement someone chose. This requirement was
never chosen, was never satisfiable, and switching it off restores the stated
intent of the zero-approval decision rather than evading it.

## Considered options

1. **Set it false and record it** (chosen) — Good, because the committed JSON
   becomes an accurate record, which is the whole reason it is committed. Good,
   because the failure it would cause is invisible until the day a commit
   arrives from an unlinked address, and then presents as an unexplained
   permanent block. Bad, because it removes a check that would have caught a
   spoofed author, which is a real if unlikely thing to give up.
2. **Leave it true and rely on the admin bypass** — Good, because it keeps a
   genuine anti-spoofing control. Bad, and disqualifying, because it makes the
   bypass routine rather than exceptional. A bypass that fires on ordinary work
   stops being an audit signal and becomes noise, which is the opposite of what
   the logged-bypass policy is for.
3. **Leave it true and say nothing** — rejected outright. The committed file
   would disagree with the live ruleset from the day it was written, in a repo
   that has no automated drift check and now documents that gap.

## Non-goals

- **No new drift check.** Comparing the live ruleset to the committed one needs
  a token with repository-admin scope, and a token that can read a ruleset is
  one step from a token that can rewrite it. The gap stays documented rather
  than closed with a credential.
- **Not revisiting the tier vocabulary.** `.github/branch-protection/**` gets an
  ordinary high rule, appended after the existing high rules so last-match-wins
  keeps its meaning.

## Cross-cutting concerns

**Security.** This is the security change. A record of which gates are required
that is not itself high tier is a gap in the same shape as a registry that does
not classify itself. Giving up the unattributed-commit check is the cost, and
it is small here: one maintainer, one machine, and every push already goes
through a pull request.

**Privacy.** None. No new data of any kind.

**Observability.** `docs/BRANCH-PROTECTION.md` gains a section naming the
parameter, the default, why it is off, and the live ruleset id, with the caveat
that ids are not stable across recreations.

## Consequences

**Good.** The committed JSON is an accurate record on the day it is written,
and the file that decides which checks are required now needs a spec, a
rollback plan and the adversarial lens to change.

**Bad.** A commit authored from an address linked to no GitHub account now
merges without an extra approval. On a repository with more than one
contributor that would be a real loss.

**Neutral.** `.github/CODEOWNERS` gains one generated line, because the
generator reads the same registry.

## Confirmation

- `python3 engine/setup/np_codeowners.py` exits 0, and
  `test_codeowners.py::test_it_matches_the_generator_byte_for_byte` fails if the
  regenerated file was not committed.
- `np_risk_tiers.tier_for(".github/branch-protection/ruleset-main.json")`
  returns `high`; `test_risk_tiers.py` already asserts no standard rule follows a
  high one.
- The live ruleset read back through
  `gh api repos/pat-browne/nervepack/rulesets/<id>` reports
  `require_extra_approval_for_unattributed_changes: false`, matching the
  committed file.

## Rollback

Find the id, then restore the parameter:

```bash
id=$(gh api repos/pat-browne/nervepack/rulesets --jq '.[] | select(.name=="main") | .id')
gh api -X PUT repos/pat-browne/nervepack/rulesets/$id \
  --input .github/branch-protection/ruleset-main.json
```

after editing the file back to `true`, or restore classic protection entirely
with the backup and the commands in `change-specs/feat-f8-tier-gate.md`.

Reverting the tier rule is a plain revert of this commit: dropping the
`.github/branch-protection/**` rule returns that path to the `normal` default,
and nothing caches a resolved tier between runs.
