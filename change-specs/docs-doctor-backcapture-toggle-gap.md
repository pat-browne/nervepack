---
id: 0036
status: accepted
date: 2026-09-14
tier: normal
blast_radius:
  - engine/nervepack_engine/np_doctor.py
  - engine/onboard/capabilities.json
  - engine/setup/tests/onboard/test_np_doctor.py
  - skills/np-core-doctor/**
---

# 0036: doctor check for the backcapture toggle

## Context and problem statement

`memory.backcapture` off silently stops real metrics and episodic capture for
weeks. Every doctor check stays green regardless.

Doctor only verifies hooks are registered. It never checks that the toggles
those hooks early-return on are actually on.

This was root-caused live on 2026-09-11 after the dashboard stopped updating.
The first fix (PR #337) documented the failure in `skills/np-core-doctor/SKILL.md`.

Two rounds of automated review flagged that prose as fragile. Exact error
strings and lock-file behavior drift when the implementation changes.

There was no tracked mechanism making doctor actually check this. Only a
runbook telling a human what to type.

## Considered options

1. Keep improving the prose (add caveats, version qualifiers, more commands).
   Bad, because each round of review found the next fragile claim. Prose
   cannot verify itself against code drift.
2. Add a doctor capability that checks `np_toggle.enabled('memory.backcapture')`
   directly. Good, because it reads the same value the hook reads, so it can
   never drift out of sync the way a written diagnosis can. Neutral, because
   it adds one more SHOULD-tier row to memorize.

## Decision

We will add `backcapture-enabled` as a SHOULD-tier core check in
`np_doctor.py`, backed by `capabilities.json`, tested in
`test_np_doctor.py`.

We will also trim `SKILL.md` to point at the check instead of walking
through manual diagnosis. Chosen option: "add a doctor check", because it
replaces a maintenance liability with a property CI keeps honest.

## Non-goals

Not fixing the SessionEnd evaluator's own reliability (Claude Code killing
slow hooks, `/exit` skipping SessionEnd). That is the reason
`backcapture-sweep` exists as a backstop at all, and is out of scope here.

## Cross-cutting concerns

- Security: none, reads a local toggle file already trusted by the process.
- Privacy: none, no new data collected.
- Observability: doctor output now surfaces this failure mode directly.

## Consequences

- Good, because the check can't go stale the way the removed prose could.
- Good, because it has test coverage (`test_backcapture_enabled_by_default_pass`,
  `test_backcapture_disabled_warns_with_fix`).
- Neutral, because the deeper root-cause narrative moved to
  `skills/np-core-doctor/references/backcapture-toggle-incident.md`.

## Confirmation

`python3 -m unittest engine.setup.tests.onboard.test_np_doctor -q` passes
(30/30).

`cli.py doctor` shows `[SHOULD] backcapture-enabled PASS` when the toggle is
on. It shows a `WARN` with the fix command when the toggle is off.

## Deviations

None.
