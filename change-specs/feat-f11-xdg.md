---
id: 0016
status: proposed
date: 2026-08-22
tier: high
blast_radius:
  - engine/setup/np_dirs.py
  - engine/setup/tests/docs/test_np_dirs.py
  - engine/setup/tests/content/**
  - engine/setup/tests/layout/**
  - engine/setup/tests/onboard/**
  - engine/nervepack_engine/**
  - engine/setup/np_*.py
  - engine/setup/np-*.py
  - engine/setup/risk-tiers.json
  - .github/CODEOWNERS
  - docs/XDG-DIRECTORIES.md
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0016: honour the XDG base directories (F11, #299)

## Context and problem statement

Nervepack reads **no `XDG_*` variable anywhere**. It hardcodes the XDG
*defaults* — `~/.config/nervepack/` and `~/.cache/nervepack/` — at **51 inline
call sites across roughly 28 files**, with no shared helper. A machine that sets
`XDG_CACHE_HOME` is silently ignored: nothing errors, the state simply lands
somewhere the user did not ask for.

What lives in those directories is the reason this needs care rather than a sed:

```
~/.config/nervepack/   toggles.local, content-dir, team-dir, adapter.json,
                       claude-oauth-token, layouts/
~/.cache/nervepack/    episodic-inbox, evaluator-inbox, session-signals,
                       backcapture-{seen,queue}, resume state, every hook log
```

A real credential and the memory pipeline's queues. Moving them by accident is
data loss, not an inconvenience.

## Decision

We will add `np_dirs.py` with `cache_dir()` and `config_dir()` and honour
`XDG_CACHE_HOME` / `XDG_CONFIG_HOME` when they are set.

**This change converts the CONFIG half only: 8 sites in 8 files.** They are the
ones that matter most and the ones there are fewest of — the OAuth token, the
toggle overrides, the content and team pointers, `adapter.json`, and the layout
manifests. The 43 cache sites (logs, queues, resume state) follow in their own
change against the same resolver.

Splitting it that way is deliberate. A 51-site edit over live state in one pass
is the shape the repo's own lesson warns about, and the config half is separable
because the resolver's defaults are byte-identical to today's paths: a
half-converted tree resolves every path exactly where it already did.

**Legacy wins when it already exists.** If `~/.cache/nervepack` is present and
the XDG-derived directory is not, the legacy path is used. This is git's own
precedence — `~/.gitconfig` takes precedence over `$XDG_CONFIG_HOME/git/config`
— and it is the only rule under which an existing install cannot silently
orphan its episodic inbox, its toggles and its OAuth token the day someone
exports `XDG_CACHE_HOME` for an unrelated program.

The cost is real and stated: a user who sets `XDG_CACHE_HOME` *intending* to
relocate an existing install will not be relocated. That is the safer of the two
surprises, because it is visible (the state is where it always was) rather than
invisible (the state is gone and the pipeline silently restarts empty).

**A relative `XDG_*` value is ignored and reported.** The XDG spec says exactly
that: such a value "should be considered invalid and ignored". It is never
normalised, because a relative path would anchor nervepack's state to whatever
directory a hook started in.

The first draft of this change *raised* instead, following Go's stdlib. See the
Deviations note: that was wrong for this codebase.

## macOS: a contested convention, and which side this picks

There is no agreed answer, and the disagreement is between serious
implementations:

- **platformdirs 4.11** lets `XDG_*` win on macOS when set.
- **Go's `os.UserConfigDir`** ignores `XDG_*` on Darwin entirely and returns
  `~/Library/Application Support`.

Nervepack today behaves like neither, because it reads nothing.

**This change follows platformdirs**: honour `XDG_*` on every platform including
macOS, and default to `~/.cache` / `~/.config` when unset. That keeps macOS
byte-identical to its current behaviour, which is what an existing install
needs, and it respects an explicit setting from a user who went out of their way
to make one. Moving macOS to `~/Library/Application Support` would relocate
every existing macOS install for a convention argument, which is not a trade
this change is willing to make.

## Considered options

1. **A resolver with legacy precedence** (chosen) — Good, because no existing
   install moves, and an explicit `XDG_*` is honoured on a fresh one. Bad,
   because the precedence is invisible: two machines with identical environments
   can resolve differently based on which directories happen to exist.
2. **Honour `XDG_*` unconditionally** — Good, because the rule is one sentence
   and has no hidden state. Bad, and disqualifying: it relocates a live
   credential and the episodic queues the first time the variable is set for an
   unrelated reason, with no error and no migration.
3. **Migrate on first run** (move the legacy directory to the XDG location) —
   Good, because it resolves the split permanently. Bad, because a half-completed
   move of a directory containing a credential is worse than either steady state,
   and every hook is a possible interruption point.

## Non-goals

- **The 43 cache sites.** Same resolver, next change. Logs and queues, not a
  credential.
- **No migration command.** Option 3's risk is the reason. A user who wants the
  state moved can move it, and the resolver will then find it.
- **`~/.claude` is untouched.** That is the host's directory, not nervepack's,
  and it belongs to #300.
- **`~/.config/Code/User/settings.json` is untouched.** It is **VS Code's**
  config, and the single most likely casualty of a pattern-based sweep here.

## Cross-cutting concerns

**Security.** `~/.config/nervepack/claude-oauth-token` is resolved through this.
A wrong answer either exposes the token at an unexpected path or makes every
scheduled job fail to find it. The resolver never creates directories and never
follows a relative value.

**Privacy.** No change to what is stored, only where it may be stored.

**Observability.** When legacy precedence fires — legacy exists, `XDG_*` is set,
and the derived directory does not exist — the resolver leaves a marker the
doctor can report, so "my `XDG_CACHE_HOME` is being ignored" is answerable
without reading source.

**Portability.** The resolver is the only place that decides, so the macOS
question above has exactly one answer in exactly one file.

## Setting HOME alone no longer isolates state

This is the consequence the change actually has, and the test suite found it
rather than the design.

Once `XDG_*` is honoured, a process that redirects `HOME` and leaves `XDG_*`
inherited resolves config and cache to the OLD location. Seven test files did
exactly that, and the shell harness has exported `XDG_CACHE_HOME` and
`XDG_CONFIG_HOME` all along, so the suite was already the shape that breaks.

Every affected test now clears or re-derives both variables alongside `HOME`.
The same applies outside the suite: a cron or wrapper that sets `HOME` to
redirect nervepack must set `XDG_*` too, or accept that it did not redirect
anything.

It is stated here rather than worked around because it is inherent to honouring
the variables at all. The alternative -- ignoring `XDG_*` whenever `HOME` looks
unusual -- is a heuristic, and a wrong one would put a credential somewhere
nobody expects.

## A new shared module has to reach every partial-tree fixture

`test_writer_implicit_fallback.sh` builds a minimal repo by copying an explicit
file list, so `np_content` importing `np_dirs` broke it with
`ModuleNotFoundError` until the copy list grew a line. Worth recording because
the failure surfaced as "cron exited non-zero -- fail-open violated", which
names neither the module nor the fixture.

## Consequences

**Good.** An `XDG_*`-configured machine gets what it asked for on a fresh
install. The 51 inline constructions collapse to two functions, so the next
question about where state lives has one place to look.

**Bad.** Precedence depends on what exists on disk, so the same environment can
resolve differently on two machines. Stated in the doc rather than hidden.

**Neutral.** Nothing moves on any existing install, on any platform. The default
paths are byte-identical to today's.

## Confirmation

- `test_np_dirs.py` asserts: unset falls back to today's paths; an absolute
  `XDG_*` is honoured; a **relative** one falls back and is reported; legacy precedence fires only
  when legacy exists and the derived directory does not; and the resolver creates
  nothing.
- A test asserts no nervepack module builds `.cache`/`.config` + `nervepack`
  inline any more, so the 51 sites cannot silently regrow.
- A test asserts `np_bootstrap.py` still names VS Code's own config path, since
  that is the one the sweep must not touch.

## Rollback

`git revert`. The resolver has no persistent state and creates no directories,
so reverting restores the previous hardcoded paths exactly — they are the same
strings the resolver returns when `XDG_*` is unset.

The only machine that can differ after a revert is one that set `XDG_*` **and**
had no legacy directory, i.e. a fresh install that wrote its state to the XDG
location. Move that directory back to `~/.cache/nervepack` or
`~/.config/nervepack` and the reverted code finds it:

```bash
mv "${XDG_CACHE_HOME}/nervepack"  ~/.cache/nervepack
mv "${XDG_CONFIG_HOME}/nervepack" ~/.config/nervepack
```

Verify with `python3 engine/nervepack_engine/cli.py doctor`, which reads the
toggle and credential paths through the same resolution.

## Deviations

- 2026-08-22 — widened to `tests/content/**`, `tests/layout/**` and
  `tests/onboard/**`. The spec declared only the new resolver's own test,
  because the design did not predict that honouring `XDG_*` would break
  isolation in tests that redirect `HOME` alone. Seven files needed it, and the
  need is the finding rather than a side effect: the same correction applies to
  any cron or wrapper that redirects nervepack by setting `HOME`.

  `spec-guard` caught this on the committed diff, after I had already run the
  full suite green. A passing suite says the code works; it says nothing about
  whether the change stayed inside what it declared.
- 2026-08-22 — a relative `XDG_*` value now **falls back and is reported**
  instead of raising. The review on #301 asked me to document the raise at three
  call sites, and three call sites wanting the same caveat was the signal that
  the caveat was the defect.

  `np_toggle` resolves through `np_dirs`, **sixteen hook modules read toggles**,
  and hooks fail open by ARCHITECTURE invariant 1. Raising would therefore have
  let one bad environment variable silently disable the entire session
  lifecycle: no error, nothing red, nothing to notice. That is the exact
  silent-total-failure shape #295 removed from hook registration, reintroduced
  one layer down.

  The XDG spec agrees with the outcome — it says ignore — so this is also the
  more standards-faithful reading. Go raises because a Go library is not sitting
  underneath sixteen fail-open callbacks.

  The doctor reports it as FAIL and names the offending value, so ignoring the
  variable does not mean hiding the mistake.
