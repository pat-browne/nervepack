# Where nervepack keeps per-machine state

Two directories, resolved in one place: `engine/setup/np_dirs.py`.

```
config_dir()   toggles.local, content-dir, team-dir, adapter.json,
               claude-oauth-token, layouts/
cache_dir()    episodic-inbox, evaluator-inbox, session-signals,
               backcapture-{seen,queue}, resume state, hook logs
```

Defaults are `~/.config/nervepack` and `~/.cache/nervepack`, unchanged from
every previous version.

## XDG is honoured

`XDG_CONFIG_HOME` and `XDG_CACHE_HOME` are read when set. Before #299 nervepack
read neither: it hardcoded the XDG *defaults* at 51 inline call sites, so a
machine that set either variable was ignored silently.

## Legacy wins when it already exists

If `~/.cache/nervepack` is present and the XDG-derived directory is not, the
legacy path is used.

This is git's own precedence — `~/.gitconfig` takes precedence over
`$XDG_CONFIG_HOME/git/config` — and it is the only rule under which an existing
install cannot orphan its state the day someone exports `XDG_CACHE_HOME` for an
unrelated program. What is at stake is a real OAuth token and the memory
pipeline's queues.

The cost is real and worth stating: someone who sets `XDG_CACHE_HOME` **intending
to relocate** an existing install will not be relocated. That is the safer of the
two surprises, because it is visible — the state is where it always was — rather
than invisible, where the state is gone and the pipeline restarts empty.

To actually move, move the directory. The resolver will then find it:

```bash
mv ~/.cache/nervepack "$XDG_CACHE_HOME/nervepack"
```

`cli.py doctor` reports when legacy precedence is in effect, so "my
`XDG_CACHE_HOME` is being ignored" is answerable without reading source.

## A relative value is ignored, and reported

```
XDG_CACHE_HOME=relative/path   ->  falls back to ~/.cache/nervepack
                                   doctor: FAIL, naming the value
```

The XDG specification says a relative value "should be considered invalid and
ignored", and that is what happens. It is never normalised: a relative path
would anchor nervepack's state to whatever directory a hook started in.

**Why it does not raise.** `np_toggle` resolves through this module, sixteen hook
modules read toggles, and hooks fail open. Raising would let one bad environment
variable silently disable the whole session lifecycle — no error, nothing red.
Ignoring keeps every hook working; the doctor keeps the mistake visible.

## macOS: a contested convention

There is no agreed answer, and the disagreement is between serious
implementations:

| | Behaviour on macOS |
|---|---|
| platformdirs 4.11 | honours `XDG_*` when set |
| Go `os.UserConfigDir` | ignores `XDG_*` entirely, returns `~/Library/Application Support` |
| nervepack before #299 | read nothing at all |

**Nervepack follows platformdirs**: `XDG_*` is honoured on every platform
including macOS, and the default stays `~/.config` / `~/.cache`.

That keeps macOS byte-identical to its previous behaviour, which is what an
existing install needs, and it respects an explicit setting from someone who went
out of their way to make one. Moving macOS to `~/Library/Application Support`
would relocate every existing macOS install to settle a convention argument.

## Windows only: two hooks moved once

`security-recall-state` and `skill-trigger-state` used to resolve with a bare
`expanduser("~")`, which on Windows prefers `USERPROFILE`. Every other hook uses
`$HOME` first, and since #302 these two do as well.

On a Windows machine where `$HOME` and `USERPROFILE` point at different places —
Git-bash is the usual reason — the old copies are left behind at:

```
%USERPROFILE%\.cache\nervepack\security-recall-state
%USERPROFILE%\.cache\nervepack\skill-trigger-state
```

Both hold recall state, which regenerates on its own, so nothing is lost by
ignoring them. They are safe to delete once the hooks have run from the new
location. **Nothing deletes them automatically**: removing files under a path
nervepack has just stopped owning is a worse failure mode than leaving two small
directories behind.

Linux and macOS are unaffected — there the two resolutions are the same path.

## One path deliberately stays outside

`~/.cache/np-core-sync-status` sits directly under `.cache`, not under
`nervepack/`. Routing it through `cache_path()` would move it, and the
`np-core-sync` skill documents that path for a human to read. A test asserts it
stays put.

## Setting HOME alone no longer isolates state

A process that redirects `HOME` and leaves `XDG_*` inherited resolves to the
**old** location. This surprised the test suite first: seven test files
redirected `HOME` while the shell harness exported both XDG variables, so they
silently kept reading the harness's directories.

A cron or wrapper that sets `HOME` to redirect nervepack must set `XDG_*` too,
or accept that it did not redirect anything.

The test harness now **unsets** both instead of exporting them. It used to export
`XDG_CACHE_HOME="$HOME/.cache"`, which is exactly what the resolver derives from
`HOME` anyway — so the exports duplicated the default while breaking isolation for
every test that redirected `HOME` on its own. Unsetting also stops a developer's
real `XDG_*` leaking into a test run, which the export had been masking.

This is inherent to honouring the variables. The alternative — ignoring `XDG_*`
whenever `HOME` looks unusual — is a heuristic, and a wrong heuristic would put a
credential somewhere nobody expects.

## The resolver creates nothing

Asking where a directory is does not make it. Callers that write already create
their own directories, and a resolver with a side effect cannot be asked a
question — nor should it create a directory as root from a cron, or under a path
someone set by mistake.

Related: `engine/setup/np_dirs.py`, `change-specs/feat-f11-xdg.md`, issue #299.
