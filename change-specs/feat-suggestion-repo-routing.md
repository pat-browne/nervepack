---
id: 0026
status: proposed
date: 2026-09-04
tier: normal
blast_radius:
  - engine/setup/np_implement_suggestion.py
  - engine/setup/np-dashboard-server.py
  - engine/nervepack_engine/cli.py
  - dashboard/index.html
  - agents/np-flow-implement-suggestion.md
  - engine/setup/tests/evaluator/**
  - docs/ARCHITECTURE.md
---

# 0026: Route a suggestion to the repo its evaluator target names

## Context and problem statement

The evaluator tags every suggestion with a `target` (`playbooks|skills|hooks|sync|other`).
The dashboard renders that tag and then drops it. The implement job always tried the
engine repo first and passed the agent nothing but the suggestion prose.

Two consequences followed. A skills or lessons change, which the directory contract puts
in the content overlay, spent its first agent pass in the wrong repo. And the agent had
to work out its own repo from which files happened to exist, with the architecture map
standing in as the marker for "this is the engine".

That inference has a dead end. An agent that answers `NOT_IMPLEMENTABLE: wrong repo,
needs content overlay` while already inside the content overlay names no repo that is
left to try. The retry then received a byte-identical prompt, so it could answer the same
way.

Observed live on 2026-09-03. The suggestion "Invoke the security-review skill as a first
step when a user requests a vulnerability review" was left open with exactly that reason.

The status ledger hid which case had happened. On a dead end the job recorded only the
first attempt's reason, so "wrong repo, needs content overlay" showed whether the overlay
had been tried and refused, or was never configured and never tried at all.

## Considered options

1. **Thread the evaluator's `target` through and let it order the attempts** — Good,
   because the tag already exists, costs nothing to forward, and saves a wasted pass.
2. **Make the agent's repo detection more reliable (more marker files)** — Bad, because
   inference stays the mechanism and the dead end survives any better marker.
3. **Ask the evaluator for a repo name directly** — Bad, because it widens the model's
   authority from picking a layer to naming a filesystem target, for no extra signal.
4. **Always try both repos and merge the verdicts** — Bad, because it doubles agent cost
   even on suggestions the first repo already satisfies.

## Decision

We will forward the evaluator's `target` from the dashboard row to the implement job,
and use it to order which repo gets the first agent pass.

Targets `skills` and `playbooks` try the content overlay first. Every other value tries
the engine first. An unknown or absent tag keeps the historic engine-first order.

We will also state the repo to the agent instead of letting it infer one. The wrapper
prepends a trusted context block naming the repo, the attempt number, and whether this is
the last repo to be tried. The agent prompt now restricts the wrong-repo verdict to
attempts that still have a repo left to redirect to.

We will record every attempted repo in the failure reason, never only the first.

Chosen option: "Thread the evaluator's `target` through", because the routing signal
already exists upstream and the only defect was that nothing carried it downstream.

## Non-goals

Changing how the evaluator picks a target. The classification is unchanged. This routes
what it already produces.

Re-opening the suggestion that exposed the bug. `cli.py suggestion-unresolve` is the
existing recovery path and needs no new code.

## Cross-cutting concerns

- Security: the tag is model-generated, so an allowlist match is the only thing it can
  do, and it may only select among nervepack's own two repos. It never builds a path or a
  command, and an off-allowlist value never reaches the prompt. The untrusted suggestion
  stays inside its nonce-delimited block, and the new context block is wrapper-generated.
- Privacy: no new data leaves the machine. The tag already lived in the local metrics.
- Observability: the failure reason now names every repo tried, which is the gap that made
  the original report undiagnosable from the dashboard.

## Consequences

- Good, because a skills suggestion reaches the overlay on its first pass.
- Good, because a dead end is now readable from the ledger alone.
- Good, because the agent stops guessing which repo it is in.
- Neutral, because an absent tag behaves exactly as before.
- Bad, because a mis-tagged suggestion spends its first pass in the less likely repo. It
  still falls through to the other one, so the cost is latency, not correctness.

## Confirmation

`engine/setup/tests/evaluator/test_implement_target_routing.py` pins the mapping, the
allowlist, the attempt order, the trusted context block, the final-attempt marker, and
that a dead end names both repos. `test_dashboard_server.py` pins that the server
forwards the tag. Both run under `engine/setup/tests/run-all.sh`.

## Rollback

Not required at this tier.

## Deviations

None.
