---
id: 0015
status: proposed
date: 2026-08-21
tier: high
blast_radius:
  - engine/setup/tests/setup/test_clean_clone_install.py
  - engine/nervepack_engine/np_hook.py
  - engine/nervepack_engine/cli.py
  - engine/setup/tests/nervepack_engine/test_np_hook.py
  - change-specs/**
---

# 0015: prove a clean clone at any path registers working hooks (F11)

## Context and problem statement

#295 replaced the literal `~/Code/nervepack` in every `hooks.manifest` row with a
`{NP_DIR}` token substituted from the resolved root. It named its own missing
proof as a non-goal: *"a CI clean-clone install from another path — the right
proof for this change, and it needs a fixture this slice does not build."*

This builds that fixture. It is #257's last unmet acceptance item that does not
require the host-adapter work.

## Why this needed a spec, which I got wrong first

I opened the pull request describing this as test-only and therefore standard
tier. `spec-guard` disagreed, and it was right.

`engine/setup/tests/setup/test_clean_clone_install.py` resolves to **high**,
because the registry's `engine/setup/*install*` rule matches it — `fnmatch`'s `*`
crosses `/`, which `risk-tiers.json` documents in as many words, and last match
wins, so that high rule beats the earlier `**/tests/**` standard rule.

Two things follow, and only one is a defect.

**Not a defect:** the registry behaved exactly as documented. A file whose name
contains `install`, under `engine/setup/`, is high tier. Over-declaring always
passes, so writing this spec at `tier: high` satisfies it honestly.

**A defect, but mine:** I ran `spec-guard` locally before `git add`, so it
diffed an empty tree and reported "exempt". A gate run against a change that does
not exist yet reports on nothing. That is the second time in this epic the same
sequencing mistake produced a false green, and it is worth writing down rather
than quietly not repeating.

The tier boundary itself is arguable — a *test for* an installer is not an
installer, and cannot change runtime behaviour. Loosening it means appending a
`**/tests/**` standard rule below the high rules, which would make every test
file standard forever, including tests for the credential and PII paths. That is
a real policy decision and does not belong in a change whose subject is
something else. Left alone deliberately; see the Deviations note.

## Decision

We will copy the engine tree to a temp path sharing no component with
`~/Code/nervepack`, run **that copy's own** `cli.py setup install-hooks` against a
temp settings file, and assert what was registered.

**A subprocess against the copy, never an in-process call.** The entire question
is what `np_paths.REPO_ROOT` resolves to, and that is computed at import from the
module's own `__file__`. An in-process call resolves to the running checkout no
matter what path the test passes, so it would pass while proving nothing. This
is the same trap the change under test exists to remove, one level up.

Six assertions, of which one carries most of the weight: **the registered
`cli.py` path must exist on disk.** A string assertion alone passes on a path
that is merely well-formed, and "well-formed but not real" is precisely the
pre-#295 failure.

## Considered options

1. **A test in the existing suite** (chosen) — Good, because `regression` and
   `windows` are both required checks and both already run this directory, so the
   property is enforced on Linux and on the Git-bash lane with no new job. Bad,
   because it copies a subtree on every suite run.
2. **A dedicated CI job doing a real `git clone`** — Good, because it is a
   literal clean clone rather than a copy. Bad, because it would need separate
   promotion into the ruleset to be enforced, and the `.git` directory here is
   31 MB, which is real time on every run for no extra coverage: the installer
   never shells out to git.
3. **Assert the manifest text instead of installing** — cheapest, and worthless.
   It would test that a file contains a token, not that a machine ends up with
   working hooks.

## Non-goals

The remaining #257 items: the 25 markdown references, the host-adapter
directory, the grep-based pre-commit check, and XDG resolution.

## Cross-cutting concerns

**Security.** None. The test writes only inside its own temp directory and
overrides `CLAUDE_SETTINGS` so it can never touch the developer's real settings.

**Privacy.** None.

**Observability.** The failure message carries the interpreter, the cli path, the
resolved root, whether the settings file exists, and both streams. This lane
cannot be reproduced locally, so an exit code alone is not diagnosable from a CI
log — which is exactly how this change's first Windows failure presented.

## Consequences

**Good.** The property #295 asserted is now enforced, on both required lanes.

**Bad.** The suite copies `engine/` per test method. Measured under a second on
Linux.

**Neutral.** The test is high tier by the registry's rules, so future edits to it
need a spec. That is a slightly odd consequence of a glob written for installers,
and it is recorded here rather than worked around.

## Confirmation

Reverting `hooks.manifest` to the pre-#295 literal form must fail this test.
Verified before opening the pull request: 3 of the 6 fail, including
`test_the_registered_paths_exist_on_disk`. A test that passes both before and
after the fix proves nothing, and that check is the only way to know which kind
this is.

## Rollback

Delete the file. It imports nothing outside the standard library and the tree
under test, and nothing imports it.

## Deviations

- 2026-08-21 — opened as a standard-tier change with no spec, on a local
  `spec-guard` run that diffed an empty tree because the file was still
  untracked. CI caught it. Spec written at `tier: high`, which the diff requires.
- 2026-08-21 — widened to `np_hook.py`, `cli.py` and `test_np_hook.py`. The test
  found a real bug in #295's own validator on its first Windows run, and fixing
  it is the only honest response to a test doing exactly what it was built to do.

  **A tilde is only special at the start of a word.** Bash expands `~/x` and
  `~user/x`; a tilde anywhere else in a word is literal. #295 rejected it
  everywhere, which broke Windows outright — 8.3 short paths are the *default*
  for a profile name over eight characters, so a Windows runner resolves its temp
  directory to `C:\Users\RUNNER~1\...` and every install there raised. Any real
  Windows user with a long username would have hit this.

  Also widened to `cli.py`, for the reason the bug took two CI rounds to find:
  `_bail` writes only to a log file. That is right for a hook, which must not
  pollute the session's streams, and wrong for a setup step, which a human or a
  CI job runs directly and reads. A failed step exited 1 with two empty streams
  and the reason in a file nobody knew to open. Setup failures now write to
  stderr as well as the log; the hook contract is untouched.
