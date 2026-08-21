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

Ruleset ids are **not stable across recreations**, so no procedure in this
document hardcodes one. Every command that needs the id looks it up:

```bash
id=$(gh api repos/pat-browne/nervepack/rulesets --jq '.[] | select(.name=="main") | .id')
```

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
Tier gate (differential gating)
```

The first five are deterministic: the same tree gives the same answer, with no
model in the loop. Only gates of that kind are ever required to pass. `Tier
gate` qualifies too — it reads verdicts and applies a table, and consults no
model.

One consequence of promoting `Tier gate` is worth knowing before it surprises
someone. A high-tier pull request whose `diff-review` SKIPPED can no longer
merge without an admin bypass, and `diff-review` always skips on a fork, because
GitHub withholds secrets from fork pull requests. So a fork pull request that
touches a hook is blocked pending maintainer action. For high-risk paths that is
the intended answer, and it is still a real narrowing.

`Spec guard` joined them in #254, and `Tier gate` in #255. It shipped advisory in #248 and ran on every
pull request after that without a false positive, which is the watch period
`change-specs/README.md` asked for.

**A required context is matched by its display name.** Renaming a job whose name
is in this list makes the old context stop reporting, and GitHub waits for it
forever. Rename the job and the ruleset in the same change.

## What is deliberately not required

`Diff review (multi-lens, advisory)` and `Auto-merge decision (standard tier)`
both run on every pull request and neither one is required.

The diff reviewer stays advisory permanently. Measured LLM review precision is
50 to 85 percent, and the largest rejection category is missing project context
rather than wrongness. It comments. It does not vote.

The auto-merge decision is not a gate at all. It records a judgement and, when
that judgement is yes, asks GitHub to enable native auto-merge. Failing it would
mean nothing.

## Auto-merge

A standard-tier pull request can merge without a human. Nothing else can.

The mechanism is **GitHub's native auto-merge**, and no code here performs a
merge. Native auto-merge is a *waiting* mechanism: GitHub holds the pull request
until every required check and every ruleset requirement is satisfied, then
merges. It sits on the same side of the gate as a human clicking the button, so
it cannot bypass one. A workflow that called the merge API directly would hold a
token able to merge whether or not the gates passed, and its safety would rest on
a conditional staying correct forever.

Four conditions decide eligibility, in `engine/setup/np_automerge.py`:

1. `tier-policy.json` says `auto_merge_eligible` — standard tier, every required
   verdict PASSED, no open problems.
2. The tier is in the policy's `allowed_tiers`.
3. The pull request's **author** is in `trusted_authors`.
4. `diff-review` ran. Not that it approved — see below.

A fifth flag, `enabled` in `engine/setup/automerge.json`, is the kill switch and
is kept separate from eligibility, so the record still says whether a change
*would* have merged itself while the switch is off. **It ships off.**

### The reviewer gets a real consequence without becoming an authority

`diff-review` never reports FAILED. What it does with a finding is post a review
comment, and this ruleset requires conversation resolution, so a pull request
with open findings is unmergeable natively and auto-merge simply waits.

Condition 4 therefore checks only that the lens *ran*. SKIPPED means no
adversarial signal exists at all, which is the one state where merging without a
human would be indefensible.

That gives a 50-to-85-percent-precision signal exactly the weight it deserves. A
finding does not block the change. It demotes the change from *merges itself* to
*a human looks at it*, so a false positive costs one glance rather than a
stranded pull request.

### Checks are verified against the latest base commit

`strict_required_status_checks_policy` means a pull request cannot merge while
its branch is behind `main`. Moving the base makes the pull request out of date
and forces an update, which re-runs every check against the new base. That is
Prow/Tide's published guarantee, obtained from the ruleset rather than from code.

### The repository setting

Native auto-merge must be on at the repository level or no pull request can use
it:

```bash
gh api -X PATCH repos/pat-browne/nervepack -f allow_auto_merge=true
```

Turning it off is the fastest way to stop every pending auto-merge at once,
without merging a change to do it.

### The ledger entry does not come from CI

`dashboard/data/ledger.jsonl` lives in the private content overlay, and a
public-repo Actions job has no write access to it and must not be given any. A
human running `np-ledger-append.py` was the mechanism, and an auto-merged pull
request has no human in the loop.

So the record catches up locally instead:

```bash
python3 engine/setup/np-ledger-append.py --repo pat-browne/nervepack --backfill
```

It appends every merged pull request the ledger is missing and skips the rest,
so running it twice is a no-op. Closing this gap by giving CI a cross-repo token
would trade a bookkeeping delay for a credential in the wrong place.

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
2. Apply it, looking the id up in the same command:
   ```bash
   id=$(gh api repos/pat-browne/nervepack/rulesets --jq '.[] | select(.name=="main") | .id')
   gh api -X PUT repos/pat-browne/nervepack/rulesets/$id \
     --input .github/branch-protection/ruleset-main.json
   ```
3. Read it back and confirm the live copy matches the committed one.

To restore the classic configuration instead, delete the ruleset and PUT the
backup:

```bash
id=$(gh api repos/pat-browne/nervepack/rulesets --jq '.[] | select(.name=="main") | .id')
gh api -X DELETE repos/pat-browne/nervepack/rulesets/$id
gh api -X PUT repos/pat-browne/nervepack/branches/main/protection \
  --input .github/branch-protection/classic-main.backup.json
gh api repos/pat-browne/nervepack/branches/main/protection --jq .required_status_checks.contexts
```

Read the last line back rather than trusting the PUT. A restore that half
applied leaves the branch protected by less than either configuration.

The committed JSON is a record of intent, not the source of truth. GitHub holds
the live state. Nothing in CI applies these files, because a workflow that could
rewrite its own required checks would be a gate that can disable itself.
