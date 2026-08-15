---
id: 0003
status: accepted
date: 2026-08-15
tier: normal
blast_radius:
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/tests/toggles/test_gate_override_toggles.py
  - change-specs/**
---

# 0003: gate override toggle (F12)

## Context and problem statement

Every hard local gate this compliance effort builds (spec-guard's local
pre-check if one lands, drift-guard, tier-guard) needs a documented way to
override it, or "ship advisory, then promote" has no safe promotion path — the
first time a real gate blocks real work with no escape hatch, it either gets
disabled outright or the session works around it silently. Neither is
acceptable; both are the exact failure this whole effort exists to prevent.

None of the three consuming hooks exist yet (drift-guard is #249, tier-guard
is part of #254, and there is no local spec-guard pre-check — #248 built a CI
job only). This change delivers the reusable mechanism they will each read
from, not the hooks themselves.

## Considered options

1. **Extend the existing toggle system** (`toggle-schema.json` +
   `np_toggle.param()`), mirroring `lessons.enforce` exactly — Good, because
   it is zero new resolver code (a three-segment dotted key already works via
   `split(".", 1)`-on-first-dot), and the dashboard settings panel already
   renders any key with a schema entry. Bad, because nothing. Neutral, because
   this makes the override mechanism itself boring — which is the point.
2. **A bespoke `gate-overrides.json` file** (my own original design, before
   reading the actual toggle system) — Good, because it could carry richer
   per-override metadata (expiry, scope). Bad, because it duplicates a
   mechanism that already exists, already has dashboard UI, already has a
   local-vs-shared precedence model, and already has an audit command
   (`cli.py toggle audit`). Rejected once the existing system was actually
   read, not assumed.
3. **Build a shared `np_gate_override.py` helper now**, for the three future
   hooks to call — Good, because it would centralize the "log regardless,
   append a ledger entry" behavior. Bad, because no real caller exists yet;
   the interface would be guessed, not derived from an actual hook's needs.
   Rejected as speculative scaffolding — #249 and #254 each build their own
   call site against these toggle keys when they land, the same way
   `lesson_guard.py` calls `np_toggle.param()` directly with no wrapper.

## Decision

We will add three bool params (`spec_guard.enforce`, `drift_guard.enforce`,
`tier_guard.enforce`) on a new `gates` feature in `toggles.conf`, plus
matching `toggle-schema.json` entries, resolved by the existing
`np_toggle.param()` machinery with zero new resolver code.

Chosen option: "extend the existing toggle system", because it is the
established precedent (`lessons.enforce`/`lesson_guard.py`) doing exactly this
job already, and reusing it costs nothing new.

## Non-goals

- **Wiring any hook's block-vs-warn logic.** No hook consumes these keys yet.
  #249 and #254 do that when they land, reading these same keys the way
  `lesson_guard.py` reads `lessons.enforce`.
- **Reaching CI-enforced required checks.** Deliberately out of scope — see
  Cross-cutting concerns below. The GitHub ruleset bypass-actor list is the
  CI-side equivalent, already built (GitHub's own feature) and already logged.
- **The `gate_override` ledger entry.** Depends on #251, not yet built. Noted
  as future work in the toggle-schema descriptions and in
  `np-flow-develop`'s `hooks.md`.
- **A shared helper module.** See option 3 above.

## Cross-cutting concerns

- **Security:** none. This changes no runtime enforcement — it adds toggle
  definitions nothing reads yet.
- **Privacy:** no personal data. `toggles.conf` is already a committed,
  public file; these three rows are as neutral as every other row in it.
- **Observability:** the "never silent" requirement (log regardless of
  enforce state) is explicitly deferred to whichever hook reads these keys
  first (#249), since there is no log call site to write yet. Recorded as a
  non-negotiable in `hooks.md` so it isn't dropped when that hook is built.

**The scope boundary is itself a security-relevant decision, not an
afterthought:** this toggle reaches local PreToolUse hooks only. It
deliberately does not, and cannot, weaken a CI-enforced required check — those
run on GitHub's runners with no access to `~/.config/nervepack/toggles.local`.
Building a parallel mechanism that did reach CI would be exactly the kind of
self-serving carve-out this compliance effort exists to prevent.

## Consequences

- Good, because #249 and #254 now have a real, tested toggle to read instead
  of inventing one under time pressure when they land.
- Good, because zero new resolver code was needed — confirmed empirically by
  running the three resolution tests against the *unmodified* `np_toggle.py`
  before adding anything, which passed immediately.
- Bad, because the toggle exists before any consumer does, which is unusual
  for this codebase's "every new feature MUST be toggleable" convention (that
  convention assumes the feature exists and needs a toggle, not the reverse).
  Justified here because #259 was filed as its own cross-cutting issue,
  explicitly blocking three others' promotion to blocking mode.
- Neutral, because `cli.py toggle audit` flags hooks missing a toggle, not
  toggles missing a hook — confirmed by reading `test_audit.py` before
  assuming it was safe to add an unconsumed toggle family.

## Confirmation

`engine/setup/tests/toggles/test_gate_override_toggles.py` (5 tests: default
resolution, local override on one key not affecting the others, missing-row
fallback, and a schema-shape check that all three keys are `type: bool` with a
description). Every existing toggle test
(`test_audit.py`/`test_cli.py`/`test_menu.py`/`test_np_toggle_resolver.py`/
`test_np_toggle_params.py`/`test_toggle_params.sh`) re-run locally to confirm
no regression. Full suite green before push.

## Deviations

None. The change stayed within the declared blast radius.
