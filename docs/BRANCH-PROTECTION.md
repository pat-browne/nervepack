# Branch protection and differential gating

`main` is governed by a **ruleset**, not by classic branch protection. The live
definition is committed at `.github/branch-protection/ruleset-main.json`, and the
classic configuration it replaced is committed next to it as a restorable
backup.

## Why a ruleset

GitHub began auto-migrating classic branch protection to rulesets in August 2026.
That migration was going to happen either way. Doing it deliberately keeps the
result under version control instead of accepting whatever the automatic
migration produces, and rulesets are the only form that records a bypass as an
audited event.

## What the ruleset requires

| Rule | Setting | Why |
|---|---|---|
| Pull request | required, **0 approvals** | Gives the PR mechanism, status checks and revert granularity. An approval requirement one maintainer cannot satisfy would only teach people to bypass it. |
| Conversation resolution | required | An unresolved review thread blocks the merge. |
| Status checks | strict, six contexts | Strict means "branch must be up to date". With one author the base branch moves only when you move it, so strict mode is nearly free. That is the inverse of the multi-author tradeoff. |
| Linear history | required | Every merge is a squash or a rebase, so `main` reads as one commit per change. |
| Force push, deletion | blocked | — |
| Bypass | repository admin, `always`, logged | See below. |

## One GitHub default is turned off on purpose

Creating the ruleset, GitHub added a parameter the committed JSON never
declared: `require_extra_approval_for_unattributed_changes`, defaulted to
`true`. It demands one approving review when a pull request contains a commit
that GitHub cannot attribute to an account, for example a commit authored with
an email address linked to no user.

With zero required approvals and one maintainer, "one extra approval" is a
requirement nobody in this repository can satisfy. A single author cannot
approve their own pull request, so any unattributed commit would leave the
change mergeable only by an admin bypass. That is precisely the unsatisfiable
approval requirement the zero-approval decision above exists to avoid, so the
parameter is set to `false` and the committed JSON now says so.

This is not the rule-relaxing the bypass policy warns against. The requirement
was never chosen, never satisfiable, and turning it off restores the stated
intent rather than escaping it.

The live ruleset id today is **21119853**, but ids are not stable across
recreations, so every command below looks it up rather than hardcoding it.

There is **no merge queue**. Queues serialize concurrent merges from several
authors. At one author they add latency and nothing else.

## Strictness is kept, bypass is logged

The rules above never get relaxed to unblock a change. When a merge has to
happen against them, the repository admin bypasses the ruleset, and GitHub
records that bypass in the rule insights log.

A bypass leaves an audit trail. A disabled rule does not. This is the whole
reason the ruleset carries an explicit bypass actor rather than running with
`enforce_admins` off, which is what the classic configuration did silently on
every admin merge.

## The six required contexts

```
Syntax sweep (stdlib-only)
Regression suite (zero-dep)
Secret/PII guard (terminal gate)
Windows suite (Git-bash)
Bash-free MCP suite (no Git-bash)
Spec guard (change-specs)
```

The first five are deterministic: the same tree gives the same answer, with no
model in the loop. Only gates of that kind are ever required to pass.

`Spec guard` joined them in #254. It shipped advisory in #248 and ran on every
pull request after that without a false positive, which is the watch period
`change-specs/README.md` asked for.

**A required context is matched by its display name.** Renaming a job whose name
is in this list makes the old context stop reporting, and GitHub waits for it
forever. Rename the job and the ruleset in the same change.

## What is deliberately not required

`Diff review (multi-lens, advisory)` and `Tier gate (differential gating,
advisory)` both run on every pull request and neither one is required.

The diff reviewer stays advisory permanently. Measured LLM review precision is
50 to 85 percent, and the largest rejection category is missing project context
rather than wrongness. It comments. It does not vote.

The tier gate is advisory for now, under this repo's rule that a new gate ships
advisory and gets promoted after it has been watched on real pull requests.
Promotion is the first step of #255.

## Differential gating

Every pull request runs the same jobs. The **tier decides which of their
verdicts are load-bearing**. See [RISK-TIERS.md](RISK-TIERS.md) for how a tier
is resolved, and `engine/setup/np_tier_policy.py` for the requirement table.

| Tier | Verdicts that must be PASSED | Extra | Merge authority |
|---|---|---|---|
| standard | the five deterministic gates | none | deterministic gates (auto-merge eligible) |
| normal | the five, plus `spec-guard` | none | human |
| high | the five, plus `spec-guard` | spec has a populated `## Rollback`; `diff-review` must have run | human, never auto-merge |

Varying the *verdicts that count* rather than the *jobs that run* is not a style
choice. A skipped required check on GitHub is indistinguishable from a pending
one, so a required check that a tier conditionally skips strands the pull
request forever. The documented workaround is a permanently-passing dummy job
for every skipped gate, which trades one confusing mechanism for two.

"`diff-review` must have run" is deliberately weaker than "must have passed".
Requiring the adversarial lens to approve would make a 50-to-85-percent-precision
reviewer a blocking authority. Requiring it to have been applied is the
strongest honest form of DORA's "subject high-risk changes to additional
scrutiny": the lens was pointed at the diff, its output is on the pull request,
and a human decides what it is worth.

## CODEOWNERS enforces nothing here

`.github/CODEOWNERS` is generated from `engine/setup/risk-tiers.json` by
`engine/setup/np_codeowners.py`. It declares the high-risk paths and routes
review requests to their owner.

It is not a gate. Required approvals are zero and the sole code owner is the
author of every pull request, so its approval role is **inert until a second
contributor exists**. GitHub also cannot vary required review count by changed
path at all: GitLab's `[Section]` syntax can require N approvals per path, and
GitHub has no equivalent. That gap is why the tier gate is computed in-repo.

Two cautions live in the generated file's own header. Its globs are copied
verbatim from a registry that uses `fnmatch`, where `*` crosses `/`, into a
format that uses gitignore matching, where `*` does not. The two disagree in
both directions on some entries. And past **3 MB** GitHub silently disables
code-owner functionality for the whole repository, with no warning of any kind.
A test asserts the file stays well under that.

## Nothing checks that the live ruleset still matches this file

There is no drift check, and this is the honest statement of a real gap rather
than a design anyone is pleased with.

CI cannot read the live ruleset. `GITHUB_TOKEN` carries no repository-admin
scope, so a workflow that wanted to compare the two would need a personal access
token with admin rights stored as a repo secret. That token would then sit in
the same job scope as everything else, and a token able to read the ruleset is
one step from a token able to rewrite it.

So the committed JSON is a record of intent and GitHub holds the truth, and the
two can silently disagree. Two habits keep the gap small:

1. Apply the file in the same session that changes it, and read the live ruleset
   back afterwards to confirm.
2. When a required check's display name changes, treat the ruleset as part of
   that change, not as follow-up work. `docs/ARCHITECTURE.md`'s change-impact
   map carries the same reminder.

## Changing any of this

1. Edit `.github/branch-protection/ruleset-main.json`.
2. Look up the id, which is not stable across recreations:
   ```bash
   gh api repos/pat-browne/nervepack/rulesets --jq '.[] | select(.name=="main") | .id'
   ```
3. Apply it:
   ```bash
   gh api -X PUT repos/pat-browne/nervepack/rulesets/<id> \
     --input .github/branch-protection/ruleset-main.json
   ```
4. Read it back and confirm the live copy matches the committed one.

To restore the classic configuration instead, delete the ruleset and PUT the
backup:

```bash
gh api -X DELETE repos/pat-browne/nervepack/rulesets/<id>
gh api -X PUT repos/pat-browne/nervepack/branches/main/protection \
  --input .github/branch-protection/classic-main.backup.json
```

The committed JSON is a record of intent, not the source of truth. GitHub holds
the live state. Nothing in CI applies these files, because a workflow that could
rewrite its own required checks would be a gate that can disable itself.
