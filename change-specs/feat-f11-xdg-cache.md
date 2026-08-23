---
id: 0017
status: proposed
date: 2026-08-22
tier: high
blast_radius:
  - engine/nervepack_engine/**
  - engine/setup/np_*.py
  - engine/setup/np-*.py
  - engine/setup/tests/**
  - docs/XDG-DIRECTORIES.md
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0017: route the cache paths through np_dirs (F11, #299)

## Context and problem statement

#301 built `np_dirs` and converted the **config** half: 8 sites holding the OAuth
token, the toggles, the layer pointers. It named the remaining work precisely —
42 cache sites across 24 files — and deferred it on the grounds that logs and
queues are not a credential and deserve their own pass.

This is that pass. There is no design left to decide: the resolver, the legacy
precedence, the relative-value handling and the macOS answer all shipped in
#301 and are unchanged here.

## Decision

We will route every remaining `~/.cache/nervepack/...` construction through
`np_dirs.cache_path()`, leaving exactly one exception.

**`~/.cache/np-core-sync-status` stays where it is.** It sits directly under
`.cache`, not under `nervepack/`, so `cache_path()` would MOVE it — and the
`np-core-sync` skill documents that path for a human to read. A test has
asserted it stays put since #301, and it still does.

## The isolation break, fixed at the source this time

#301 discovered that honouring `XDG_*` means a process redirecting `HOME` alone
no longer isolates state, and fixed it by patching seven test files.

Converting the cache half made that fix insufficient: eight more tests broke the
same way, because far more of the suite reads cache paths than config paths.
Patching them one by one would have been the third round of the same edit.

The actual cause was in the harness. `np_hermetic_env` exported
`XDG_CACHE_HOME="$NP_TEST_HOME/.cache"` and `XDG_CONFIG_HOME="$NP_TEST_HOME/.config"`
— which is exactly what `np_dirs` derives from `HOME` when they are unset. The
exports duplicated the default and broke every test that redirected `HOME` on its
own.

The harness now **unsets** both and creates the directories under `HOME`
directly. That fixes all eight without touching them, and closes a second hole
the exports were masking: a developer with a real `XDG_CACHE_HOME` in their shell
would previously have had it overridden, and would now have it leak in. Unsetting
handles both.

## Two hooks change behaviour on Windows, and that is the fix

`security_recall.py` and `skill_trigger_recall.py` resolved their state with a
bare `os.path.expanduser("~")`. Every other hook uses
`os.environ.get("HOME") or os.path.expanduser("~")`, and `np_dirs` follows the
majority.

On Linux and macOS the two are the same. **On Windows they are not** — Python's
`expanduser` prefers `USERPROFILE`, so those two hooks were writing their state
somewhere no other hook did. The Windows CI lane is what surfaced it: their tests
asserted the old resolution and failed once the hooks went through `np_dirs`.

The tests now assert the HOME-first form, because the hooks agreeing with each
other is the correct outcome rather than a regression to absorb. The consequence
is that on a Windows machine where `$HOME` and `USERPROFILE` differ, those two
state files resolve somewhere new. Both hold recall state — which skills were
surfaced recently — which regenerates on its own, so nothing is lost.

## Considered options

1. **Unset in the harness** (chosen) — Good, because one line fixes eight tests
   and the developer-environment leak at once, and it removes a duplicated
   default rather than adding a workaround. Bad, because a test that genuinely
   wants to exercise `XDG_*` must now set it itself, which is correct but is a
   change in what the harness guarantees.
2. **Patch the eight tests** — Good, because it touches nothing shared. Bad,
   because it is the same edit for the third time, and the next subsystem to be
   converted would need it a fourth.
3. **Have `np_dirs` ignore `XDG_*` when `HOME` was redirected** — rejected
   outright. That is a heuristic about intent, and a wrong one puts state
   somewhere nobody expects.

## Non-goals

- **No behaviour change.** With `XDG_*` unset, every path resolves byte-for-byte
  where it did before this change and before #301.
- **The sync status file.** See above.
- **`~/.claude`.** The host's directory, and #300's subject.

## Cross-cutting concerns

**Security.** No credential moves here; the token was #301's. The risk in this
pass is a wrong path for a queue or a lock, which shows up as a hook silently
doing nothing — so the conversion was verified per-site rather than trusted.

**Observability.** The doctor already names a non-default cache directory, from
#301.

**Portability.** Nine files needed an import placed after their own `sys.path`
bootstrap rather than in the stdlib block, and two needed a bootstrap that
reached `engine/setup` at all. Both were found by the suite rather than by
reading, which is recorded below.

## Consequences

**Good.** All 50 sites now resolve in one place. The inline-construction guard in
`test_np_dirs.py` covers both directories, so neither can regrow.

**Neutral.** The harness no longer guarantees `XDG_*` is set. Any future test
that wants them must say so, which `test_mcp_lifecycle.py` already did.

## Confirmation

- `test_np_dirs.py::test_no_module_builds_either_dir_inline` fails on a planted
  regrowth. Verified by planting one and watching it fail.
- The `np-core-sync-status` and VS Code exclusions are each asserted by a test
  that predates this change.
- 168 tests pass with the harness no longer exporting `XDG_*`.

## Rollback

`git revert`. Nothing moves either way: with `XDG_*` unset the resolver returns
the same strings the inline constructions built, which is what makes this
revertible without touching any state on disk.

The harness change reverts with it. A machine mid-way between the two — reverted
code, unset variables — is the ordinary case and resolves identically.

## Deviations

- 2026-08-22 — blast radius includes `engine/setup/tests/**` rather than the
  named test file. The harness fix is in `_lib/harness.sh`, which the spec did
  not anticipate needing because #301's approach had been to patch tests
  individually. Discovering that approach did not scale is the substance of this
  change.
