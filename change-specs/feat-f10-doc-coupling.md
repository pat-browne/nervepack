---
id: 0013
status: proposed
date: 2026-08-20
tier: high
blast_radius:
  - engine/setup/doc-coupling.json
  - engine/setup/np_doc_coupling.py
  - engine/setup/np-doc-coupling-gate.py
  - engine/setup/tests/docs/test_doc_coupling.py
  - engine/setup/risk-tiers.json
  - .github/CODEOWNERS
  - .github/workflows/ci.yml
  - docs/DOC-COUPLING.md
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0013: documentation-coupling check (F10)

## Context and problem statement

Criterion 03 grades Strong on active pruning. Its one soft edge is that
documentation landing in the same commit as the change is a **checklist
convention, not enforced coupling**. Standards here land as separate
`skill(<name>):` commits, so the convention is already not what happens.

The finding that shapes the design is Wen et al., ICPC 2019 — 1.3 billion
AST-level changes across the complete history of 1,500 systems, with 500 commits
hand-analyzed. Many documentation inconsistencies arrive as a **side effect of
refactoring**, not of feature work. A *replace magic number* refactoring removes
the constant from the code and leaves it in the comment. A class-hierarchy
refactoring leaves dangling type references.

**A coupling check keyed only to feature paths systematically misses the
dominant case.**

## Decision

We will ship two rules, not one, because the dominant case needs a different
shape of rule from the obvious case.

**Rule 1, triggers.** A change touching an enumerated trigger path is expected
to carry a documentation change in the same diff. The trigger list is committed
as data in `engine/setup/doc-coupling.json` and enumerated GitLab-style, so the
rule is auditable rather than a slogan. Docs are expected when a change
introduces or enhances user-facing behavior, changes an interface, changes a
documented process, or deprecates something. **Backend-only is exempt.**

**Rule 2, dangling references.** When a diff deletes or renames a file, and a
documentation file names that path, and the diff does not also touch that
documentation file, the documentation is now wrong. This is the refactor case,
and it is checked by exact reference rather than by guessing whether a diff
"looks like" a refactor.

Rule 2 is where the ICPC finding lands. We considered detecting refactor-shaped
diffs heuristically — balanced insert and delete counts, no new public names —
and rejected it. Every such heuristic is wrong often enough to be ignored, and a
check that gets ignored protects nothing. A renamed file that a document still
names by its old path is not a heuristic. It is a fact about the tree.

## The consequence is an issue, not a red X

The check is **advisory**. It never blocks.

That is not timidity, it is the measured behaviour of every comparable gate.
GitLab runs a real hard gate on documentation and still had to build an escape
hatch, the three-day rule. Danger's canonical example ships a `#trivial` bypass.
Both are admissions that unconditional gates get disabled. With one maintainer
holding the admin bit, a blocking documentation gate would be overridden the
first time it was inconvenient and disabled the second.

So the automated consequence is **cheap and non-negotiable rather than severe
and dismissible**: on merge, an unmet coupling opens an issue that links the
merged change and names the specific files. A red X can be dismissed and leaves
nothing behind. An open issue has to be closed by someone, and until it is, the
debt is visible in the same place all the other work is.

Deferred documentation work is therefore **recorded, not forgiven**.

## Why the issue opens on merge, not on the pull request

Opening an issue from a pull request job would file one on every push to the
branch, and would hand `issues: write` to a job that runs on pull-request-derived
input. The check runs advisory on the pull request, where its output is a
comment and a gate verdict, and the issue opens from the `push` to `main` that
merged it. By then the change is a fact and there is exactly one of it.

## Considered options

1. **Trigger list plus dangling-reference check, advisory, issue on merge**
   (chosen) — Good, because the two rules cover the two measured failure shapes
   and neither is a heuristic. Good, because the consequence survives a
   maintainer who can override anything. Bad, because an issue per unmet
   coupling can accumulate, and a pile of stale open issues is its own kind of
   noise.
2. **A blocking CI gate** — Good, because coupling would be guaranteed. Bad,
   and disqualifying, for the GitLab and Danger evidence above: it would be
   bypassed and then removed, and the removal would be quiet.
3. **A PR-template checklist** — this is what exists today. It is the thing
   being replaced, and its failure is the reason for this issue.

## Non-goals

- **Not a link checker.** `lychee` is named in #256 as also worth taking and is
  a genuinely separate mechanism: a scheduled sweep of a whole tree, not a
  per-change coupling rule. It gets its own change.
- **Not a `last_reviewed:` freshness field.** Also named in #256, also separate,
  and it verifies that someone looked rather than that the content is right.
- **No refactor heuristic.** See above.
- **No documentation content check.** This checks that a document was touched.
  Nothing here can tell whether what was written is true.

## Cross-cutting concerns

**Security.** The gate reads the diff and the tree. The merge-time job needs
`issues: write`, which is why it runs on `push` to `main` and never on
pull-request-derived input. `doc-coupling.json` classifies itself `high`, like
every other file that decides how much scrutiny a change gets: a trigger list
that can be emptied in a standard-tier diff is not a trigger list.

**Privacy.** None. Paths already public in the diff.

**Observability.** The check emits an F4 gate verdict on every pull request,
passing or not. The issue it opens on merge names the trigger that fired and the
files involved, so the reader does not have to re-derive why.

## Consequences

**Good.** The dominant measured source of documentation drift — refactoring —
gets a check aimed at it specifically, rather than a feature-path rule that
would miss it.

**Bad.** Rule 2 scans documentation for path strings, so it is quadratic in
(files removed x documentation files). On this tree that is milliseconds. On a
much larger one it would need an index.

**Bad.** An unmet coupling on a merge opens an issue whether or not the author
already intends to write the doc. Closing it is one click, but it is a click.

**Neutral.** The trigger list starts deliberately small. A list that fires on
everything teaches people to ignore it, and this mechanism only works while its
output is believed.

## Confirmation

- `test_doc_coupling.py` asserts each trigger fires on its own paths and not on
  others, that a diff carrying a documentation change satisfies the trigger,
  that a renamed file still named by a document is reported, and that renaming a
  file *and* updating the document that names it is clean.
- The same test asserts `doc-coupling.json` resolves to `high`.
- The gate's own pull request is a live case: it changes `ci.yml`, a documented
  process, and carries `docs/DOC-COUPLING.md`.

## Rollback

**Stop it firing, with no deploy.** Set `"enabled": false` in
`engine/setup/doc-coupling.json`. It is the first thing the gate reads.

**Stop it opening issues while keeping the check.** Remove the
`doc-coupling-issue` job from `ci.yml`. The pull-request job is unaffected and
keeps emitting verdicts.

**Remove it entirely.** Delete both jobs. `np_doc_coupling.py` and
`np-doc-coupling-gate.py` are inert if unreferenced — nothing imports them but
that job and their tests — and `doc-coupling.json` is read by nothing else.

No state to unwind: the check writes no file outside the workflow run, and any
issues it already opened are ordinary issues that can be closed.
