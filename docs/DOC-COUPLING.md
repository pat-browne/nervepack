# Documentation coupling

A change that alters what someone has to know should carry the documentation
change with it. This check looks for that, and when it does not find it, opens
an issue.

It never blocks anything.

## Two rules, because there are two failure shapes

**Rule 1 — triggers.** A change touching an enumerated path is expected to carry
a documentation change in the same diff. The list lives in
`engine/setup/doc-coupling.json`, committed as data so it can be read and argued
with rather than guessed at.

Documentation is expected when a change does one of four things: introduces or
enhances user-facing behavior, changes an interface, changes a documented
process, or deprecates something. **Backend-only is exempt**, and that exemption
is why the trigger list is short and specific instead of a catch-all on source
paths.

**Rule 2 — dangling references.** When a change deletes or renames a file, and a
document names that path, and the change does not also touch that document, the
document is now wrong.

## Rule 2 is the one that matters

Wen et al. (ICPC 2019) studied **1.3 billion AST-level changes across the
complete history of 1,500 systems**, with 500 commits analysed by hand. Many
documentation inconsistencies arrive as a **side effect of refactoring**, not of
feature work. A *replace magic number* refactoring removes the constant from the
code and leaves it in the comment. A class-hierarchy refactoring leaves dangling
type references.

A coupling check keyed only to feature paths systematically misses that, which
is the dominant case.

Detecting "this diff looks like a refactor" was considered and rejected. Every
heuristic for it — balanced insert and delete counts, no new public names — is
wrong often enough to be ignored, and a check that gets ignored protects
nothing. A removed path that a document still names is not a heuristic. It is a
fact about the tree.

## Advisory, permanently

This one is not advisory pending promotion, the way `spec-guard` and `tier-gate`
were. It stays advisory.

GitLab runs a real hard gate on documentation and still had to build an escape
hatch, the three-day rule. Danger's canonical example ships a `#trivial` bypass.
Both are admissions that unconditional gates get disabled. With one maintainer
holding the admin bit, a blocking documentation gate would be overridden the
first time it was inconvenient and removed the second.

## So the consequence is an issue

On merge, an unmet coupling opens one issue that names the trigger that fired
and the files involved.

A red X can be dismissed and leaves nothing behind. An open issue has to be
closed by someone, and until it is, the debt is visible in the same place as all
the other work. Deferred documentation is **recorded, not forgiven**.

Closing it by writing the documentation is one option. Closing it with a
sentence saying why none was needed is the other. Both are decisions. Leaving it
open is not.

## Why the issue opens at merge

Opening it from a pull-request job would file one on every push to the branch,
and would hand `issues: write` to a job running on pull-request-derived input.

On the pull request the check runs advisory and its output is a gate verdict. The
issue opens from the `push` to `main` that merged the change, where the change is
a fact and there is exactly one of it. A re-run does not file a second copy —
the opener looks for an open issue whose body already names that commit.

## The trigger list

| Trigger | Fires on | Why |
|---|---|---|
| `cli-surface` | `cli.py`, `engine/setup/np-*.py` | a user-facing command's flags or behavior |
| `lifecycle-hooks` | `**/hooks/**`, `hooks.manifest` | changes what happens inside a session without anyone asking |
| `documented-process` | `.github/workflows/**`, `.github/branch-protection/**` | CI is a documented process, described in [BRANCH-PROTECTION.md](BRANCH-PROTECTION.md) |
| `toggles` | `toggles.conf`, `toggle-schema.json` | a toggle is an interface: someone has to know it exists |
| `policy-data` | `risk-tiers.json`, `automerge.json`, `doc-coupling.json` | the files that decide how much scrutiny a change gets |
| `installers-and-scheduling` | `*install*`, `*cron*`, `np_scheduler*` | mutates the machine outside the repo |

`change-specs/**` counts as documentation. A change spec is where a normal- or
high-tier change explains itself, and demanding a second document on top of it
would be ceremony.

Tests are exempt. A test-only diff is backend-only by definition, and it cannot
introduce user-facing behavior, which is the first of the four conditions.

**The list starts small on purpose.** A trigger that fires on everything teaches
people to ignore the check, and this mechanism works only while its output is
believed. Add a trigger when a real drift gets through, not in anticipation.

## Turning it off

```json
{ "enabled": false }
```

in `engine/setup/doc-coupling.json`. It is the first thing the check reads. To
keep the check but stop the issues, delete the `doc-coupling-issue` job from
`ci.yml`.

## What this cannot do

It checks that a document was **touched**. Nothing here can tell whether what
was written is true, or whether it describes the change that was actually made.
That remains a human judgement, and no gate in this repository claims otherwise.

Related: `engine/setup/doc-coupling.json` (the list),
`change-specs/feat-f10-doc-coupling.md` (the argument),
[BRANCH-PROTECTION.md](BRANCH-PROTECTION.md) (where the other gates live).
