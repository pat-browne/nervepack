---
id: 0007
status: accepted
date: 2026-08-19
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/drift_guard.py
  - engine/nervepack_engine/cli.py
  - engine/setup/np_change_spec.py
  - engine/setup/np-spec-guard.py
  - engine/setup/hooks.manifest
  - engine/setup/tests/**
  - docs/ARCHITECTURE.md
  - change-specs/**
  - skills/np-core-doctor/references/log-patterns.md
---

# 0007: spec-drift PreToolUse hook (F3)

## Context and problem statement

F2 built `spec-guard` as a CI job. It reads the same `blast_radius` this hook
will read, and it reads it correctly — but it reads it after the work is done.
Between the first out-of-radius edit and the CI verdict, an agent completes a
whole task. The diff that arrives at CI is not a drift signal any more, it is a
finished change that has to be unpicked.

The failure is specific to agent execution. A stale plan makes an agent
confidently execute work that no longer matches reality without flagging
anything. A human reviewer notices the mismatch and stops; an agent does not.
Nothing in superpowers detects this — `executing-plans` stops on a blocker, and
silent drift does not present as a blocker.

Prose does not close this gap. Advisory memory has already failed twice in this
repo (trunk-freshness and superpowers-first, both 2026-08-12). A gate a session
can talk itself out of is not a gate.

## Considered options

1. **A PreToolUse hook on Write and Edit that resolves the spec from the edited
   file's own repo and branch, and denies a path outside `blast_radius`** —
   Good, because it fires at the moment of the edit, which is the entire point
   of the feature, and because it can reuse F2's matcher so local and CI cannot
   disagree. Good, because resolving the spec from the edited path makes the
   hook self-scoping: a repo with no `change-specs/` directory is unaffected.
   Bad, because it makes a second blocking hook, and ARCHITECTURE invariant 1
   permits exactly one. Neutral, because it is inert on every repo on this
   machine except nervepack.

2. **A local `pre-commit` git hook** — Good, because it costs nothing per edit
   and uses a standard mechanism. Bad, because it fires after the task is
   finished, which is the latency F3 exists to remove; the whole argument for
   this feature is that CI is too late, and a pre-commit hook is only slightly
   earlier. Bad, because a git hook is not installed by cloning, is bypassed by
   `--no-verify`, and cannot name the tool call that caused the drift.
   Rejected.

3. **A PreToolUse hook that only ever warns** — Good, because it cannot brick a
   session. Bad, because a warning is advisory memory with extra steps, and
   advisory memory is the documented prior failure this feature answers. The
   issue's first acceptance criterion is "blocks the edit". Rejected as the
   default posture, and kept as the behavior when
   `gates.drift_guard.enforce` is off.

## Decision

We will add `engine/nervepack_engine/hooks/drift_guard.py`, a PreToolUse hook
registered for Write and Edit, dispatched as `cli.py hook drift-guard`.

From the edited file's absolute path it walks up to the repository root, reads
the current branch, and looks for `change-specs/<branch-slug>.md`. When that
file declares a `blast_radius` and the edited path matches none of its globs,
the hook returns `permissionDecision: "deny"` naming the path and the two legal
responses: widen the radius with a `## Deviations` entry, or supersede the
spec. It never widens the radius itself.

Three sub-decisions, each departing from something written down elsewhere:

**We will factor the matcher into `engine/setup/np_change_spec.py`** and import
it from both this hook and `np-spec-guard.py`. If the local gate and the CI gate
compute the blast radius differently, one of them is lying about the same
policy. This is a real second caller, not anticipatory factoring.

**We will read the branch from `.git/HEAD` directly, not from `git
rev-parse`.** This hook runs on every Write and Edit. A subprocess costs 10–20ms
of that budget and buys nothing a file read does not give.

**We will not build the per-session spec cache** the issue asks for. That
criterion assumes a long-lived process. A PreToolUse hook is a fresh process per
invocation, so the cache would have to live on disk, and a disk cache costs a
read plus a write to avoid one small read — strictly slower than the thing it
optimizes. Reading the spec on each invocation is cheaper and inherently
always-fresh, which is what the mtime check existed to guarantee.

Chosen option: "A PreToolUse hook on Write and Edit", because it is the only
option that acts before the drift becomes a finished change, and because
sharing F2's matcher costs one small module and removes a whole class of
local-versus-CI disagreement.

## Non-goals

**Enforcing the risk tier.** Blocking `git merge` and `git push` by tier is
tier-guard, a PreToolUse hook on Bash, and it belongs to #254. This hook reads
`blast_radius` and ignores `tier`.

**Checking that a spec exists at all.** `spec-guard` already fails a non-exempt
PR with no spec, and it can see the whole diff, which a per-edit hook cannot. A
missing spec here means "this repo has not adopted the convention", which is the
common case on every other repo on the machine. The hook stays silent.

**Guarding every write path.** An agent can still write a file through Bash
(`cat > file`), through an MCP tool, or through `NotebookEdit`. Registering the
broad `mcp__.*` matcher would fire this hook on every MCP call in every session
to inspect a `file_path` that mostly is not there. This raises the cost of
silent drift; it does not make drift impossible, and claiming otherwise would
be the misleading-evidence failure this epic exists to avoid.

**Bounded logging, against the issue's wording.** The issue asks for "every bail
and every pass" in the log. Taken literally that is one line per Write and Edit
in every session on this machine, the overwhelming majority from repos with no
change spec at all. We will log every deny, every warn, and every pass where a
spec was found and actually adjudicated. "No spec here" is not a bail, it is the
hook correctly deciding it has no jurisdiction, and it stays silent.

## Cross-cutting concerns

- **Security:** the `blast_radius` globs are attacker-reachable input in the
  general case — a spec file arrives inside a repo, and a repo can come from
  anywhere. They are never executed and never used to construct a path. They
  are matched with `fnmatch`, which does compile them to a regex internally, so
  the accurate claim is narrower than "no regex": a `.` or `+` in a glob is
  matched literally, and a caller cannot inject regex syntax through one. The
  residual exposure is backtracking on a pathological glob, bounded by a path
  length of a few thousand characters and by `fnmatch`'s own pattern cache;
  `np-spec-guard.py` has carried the identical exposure in CI since F2. The hook
  only ever widens what is *allowed*, so a malicious spec can at worst disable
  the guard for its own repo — the same authority its author already has by
  deleting the file. An edit whose realpath falls outside the resolved
  repository root is not adjudicated at all.
- **Privacy:** the log line holds an absolute file path and a branch name, under
  `~/.cache/nervepack/`. Same class as every other hook log, and no transcript
  content, no file contents, no diff.
- **Observability:** `~/.cache/nervepack/drift-guard.log`, one dated line per
  adjudication, in the shape `np-core-doctor`'s `references/log-patterns.md`
  already decodes.

## Consequences

- Good, because it is the first mechanism in this repo that catches drift while
  it is still one edit rather than a finished branch.
- Good, because the local and CI gates read one matcher, so a spec that passes
  locally cannot fail CI on radius alone.
- Bad, because it is a second blocking hook, and every blocking hook is a fresh
  chance to brick a session. Bounded the same four ways `turn_gate` is: toggle
  gated, silent where it has no jurisdiction, one decision per tool call, and
  every internal error path returns allow.
- Bad, because it adds **~75ms to every Write and Edit** on the machine, in
  every repo, forever. Measured, not estimated: 10 dispatches in 0.75s against a
  0.11s floor for 10 bare interpreter starts. The hook's own work is
  microseconds; the cost is `cli.py`'s import graph, which `lesson-guard`
  already pays on these same two tools. Cutting it means making dispatch lazy
  for all hooks, which is a separate change and a separate argument.
- Neutral, because it is inert until a repo adopts `change-specs/`. Only
  nervepack has.

## Confirmation

- `engine/setup/tests/nervepack_engine/test_drift_guard.py`: in-radius edit
  allows; out-of-radius edit denies and names the path; `enforce=off` downgrades
  the same input to a warn; and each fail-open path (no repo, no spec, no
  `blast_radius`, unreadable HEAD, malformed payload) returns allow.
- `engine/setup/tests/nervepack_engine/test_np_change_spec.py`: the shared
  matcher, including that `np-spec-guard.py` and the hook agree on the same
  (path, globs) pairs.
- `grep -c 'hook drift-guard' engine/setup/hooks.manifest` returns 2.
- The existing `spec-guard` CI job stays green on this branch, which is the
  regression check on the `np-spec-guard.py` refactor.
- Dogfood: this spec's own `blast_radius` is the policy the hook enforces
  against this branch while the branch is being built.

## Rollback

Ordered cheapest first.

1. **No code change, immediate.** Add `gates.drift_guard.enforce=off` to
   `~/.config/nervepack/toggles.local`. Every deny becomes a warn; the hook
   still logs. `gates=off` disables the family.
2. **Local, no revert.** Delete the two `PreToolUse|Write` / `PreToolUse|Edit`
   drift-guard rows from `engine/setup/hooks.manifest` and run `cli.py setup
   install-hooks`. The hook is no longer invoked at all.
3. **Full.** Revert the merge commit. The hook, the manifest rows, the shared
   module, and the invariant amendment go together; `np-spec-guard.py` returns
   to its inlined matcher in the same revert.

## Deviations

- 2026-08-19 — also touched `skills/np-core-doctor/references/log-patterns.md`.
  Reason: the spec's own Observability section promises the log is decodable by
  `np-core-doctor`, and that file documents only two of nervepack's logs today,
  so the promise was unmet until a third section landed. Blast radius widened.
  Caught by running this branch's own hook against the edit before making it —
  the deny is reproduced in the PR body.
