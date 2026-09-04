---
id: 0026
status: accepted
date: 2026-09-04
tier: standard
blast_radius:
  - engine/setup/tests/evaluator/test_dashboard_lifecycle.py
  - change-specs/fix-dashboard-lifecycle-popen-tracker.md
---

# 0026: Count only backend spawns in the dashboard-lifecycle Popen tracker

## Context and problem statement

`test_repeated_session_starts_do_not_spawn_a_second_backend` fails on macOS with
`AssertionError: 4 != 2` on a clean `main`, and passes on Linux. The test wraps
`Popen` to count how many times the lifecycle spawns `np-dashboard-server.py`,
then asserts three hook runs spawn it once.

`mock.patch.object(np_dashboard.subprocess, "Popen", ...)` patches the shared
`subprocess` module object, not a per-module alias, so every `subprocess.run()`
reached from the code under test lands in the tracker too. `np_dashboard.boot_id()`
falls back to `sysctl -n kern.boottime` when `/proc/sys/kernel/random/boot_id` is
absent, and `open_dashboard.run()` calls it once per invocation. Instrumenting the
tracked argv shows one server spawn plus three `sysctl` runs — the observed 4.

On Linux `boot_id()` reads `/proc` and spawns nothing, so the count is 1 == 1 and
CI stays green. The port-reuse guard itself is correct: `dashboard_url()` probes
the port once and only spawns when nothing answers.

## Considered options

1. Filter the tracker to argv containing `np-dashboard-server.py` — Good, because it
   matches the tracker's stated purpose (hold the server handles for teardown) and
   makes the assertion host-independent. Neutral, because it adds an argv check.
2. Patch `np_dashboard.boot_id` in `setUp` — Bad, because the test deliberately
   exercises the real `boot_id()` so the marker it burns matches the live boot; that
   marker match *is* the drift condition under test.
3. Patch a narrower target than the `subprocess` module — Bad, because
   `np_dashboard` imports the module, not the symbol, so there is no narrower seam
   without changing production code to suit the test.
4. Make `boot_id()` not shell out on macOS — Bad, because it is the documented,
   deliberate behavior change that restored dashboard auto-open on macOS, and
   nothing about it is broken.

## Decision

We will filter the tracking `Popen` wrapper to record only spawns whose argv names
`np-dashboard-server.py`.

Chosen option: "Filter the tracker to backend spawns", because the defect is in the
test's isolation, not in the port-reuse guard, and the guard's contract is about
backend processes only.

## Non-goals

Changing `np_dashboard.py` or `open_dashboard.py`. Both behave correctly; the
composed contract the file guards still holds. Also not in scope: auditing other
suites for the same shared-module patch pattern.

## Cross-cutting concerns

- Security: none. Test-only.
- Privacy: none.
- Observability: teardown still reaps every server handle, so the suite cannot leak
  a detached listener onto the host.

## Confirmation

`python3 engine/setup/tests/evaluator/test_dashboard_lifecycle.py` passes on macOS
and stays green on the Linux CI lane. Mutation-checked: reverting
`dashboard_url()`'s `if not listening:` guard to an unconditional spawn turns the
test red again, so the filter narrows the count without blunting the assertion.

## Rollback

n/a — standard tier.

## Deviations
