---
id: 0030
status: proposed
date: 2026-09-08
tier: normal
blast_radius:
  - engine/nervepack_engine/np_sync.py
  - engine/setup/tests/sync/test_np_sync.py
  - skills/np-core-sync/references/scope-and-caveats.md
  - change-specs/**
---

# 0030: The post-pull steps must run fresh, and must run for every layer

## Context and problem statement

Two defects in the same function family, filed separately, that compound.

#243: the post-pull steps ran stale code. `cli.py` imports `np_link_skills`,
`np_hook` and `np_generate_index` at module scope, before any dispatch.
`_post_ff_steps` then called two of them in-process, after the fast-forward
had already updated those files on disk. Python caches modules in
`sys.modules`, so the sync that pulled a fix to a post-pull step ran the
pre-fix version of it. On 2026-08-14 that was unrecoverable within the run:
#242 fixed `INDEX.md` deleting rows, and syncing that fix down deleted the 20
`dp-*` rows again, because the repair carries rows over from the existing file
and the stale run had already destroyed them.

#284: the post-pull steps never ran at all for a content-layer pull.
`_post_ff_steps` had exactly one call site, on the engine fast-forward path.
The overlay takes `_content_sync` to `_ff_only_layer_sync`, which returns
without relinking. The overlay is where most skills live, so the layer that
most often gains skills is the one whose sync cannot install them.

They compound. #243 means a pulled fix to the linker applies late. #284 means
the linker may not be invoked at all on the run that pulled new skills.

## Considered options

1. Run the Python steps as subprocesses from the synced target, and return
   from `_ff_only_layer_sync` whether it moved — Good, because the subprocess
   pattern is already in this function for the bash installers, and freshness
   comes from the process boundary rather than from knowing which modules a
   future change might touch. Good, because a layer that moved is the exact
   condition for a relink.
2. `importlib.reload()` the affected modules — Bad, because reload order
   matters and transitive imports are easy to miss. `np_generate_index` is
   reached through `np_link_skills`, which is how #242 got hit.
3. Re-exec the sync itself after a fast-forward — Neutral. It makes every step
   fresh by construction, but it is the heaviest option and changes the
   process model of a hook that runs at SessionStart.

## Decision

We will run each Python post-pull step as `cli.py setup <step>` in a fresh
process from the synced target, and we will relink after any layer
fast-forwards, not only the engine's.

`_ff_only_layer_sync` returns True only when HEAD actually moved. Already
level is False, because nothing arrived and there is nothing new to link.

Chosen option: "subprocess plus a moved-layer signal", because it matches the
pattern already in the function and needs no per-module knowledge.

## Non-goals

Re-installing OS scheduler artifacts. A process boundary makes code fresh. It
does not rewrite a plist or a crontab entry, and re-onboarding is still what
does that. The caveats doc now says so in both directions.

Relinking on a layer that was already level. That would be free, but "moved"
is the honest condition and a wrong signal is worse than an extra call.

## Cross-cutting concerns

- Security: the subprocess runs `cli.py` from the synced target by absolute
  path, with no shell, and is skipped when that file is absent.
- Privacy: none.
- Observability: the steps stay best-effort, but a non-zero exit writes an
  stderr note naming the step, the code and the first line of its own stderr.
  Discarding it would leave skills unlinked while sync reported a clean
  fast-forward, which is the failure shape this spec exists to remove. Same
  channel `_ff_only_layer_sync` already uses for a layer it could not pull.

## Consequences

- Good, because a pulled fix to a post-pull step applies on the run that pulls
  it, instead of one sync later.
- Good, because a new overlay skill is linked by the sync that pulled it.
- Bad, because two process spawns replace two in-process calls on every engine
  fast-forward. A fast-forward is rare and already spawns git and bash.
- Neutral, because `io` and `np_link_skills` are no longer imported by
  `np_sync.py`.

## Confirmation

`engine/setup/tests/sync/test_np_sync.py`: a stub `cli.py` planted in the
synced target records each `setup <step>` call, which only a fresh process
from that tree can reach. Four tests assert an engine fast-forward runs
link-skills then install-hooks, a content-layer fast-forward relinks with the
engine unmoved, an already-level overlay does not, and a target with no engine
tree still fast-forwards and reports normally.

A fifth test asserts every step name `np_sync` passes resolves in `cli.py`'s
setup table. Nothing else couples the two, and a renamed step would make every
post-pull run a silent no-op again.

Both new behaviour tests were run against the pre-fix `np_sync.py` and fail
there with an empty call list.
