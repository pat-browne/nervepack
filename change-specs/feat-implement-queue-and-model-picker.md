---
id: 0042
status: accepted
date: 2026-09-29
tier: high
blast_radius:
  - AGENTS.md
  - agents/np-flow-skill-maintain.md
  - dashboard/index.html
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - CHANGELOG.md
  - change-specs/feat-implement-queue-and-model-picker.md
  - engine/nervepack_engine/np_capture.py
  - engine/nervepack_engine/np_doctor.py
  - engine/nervepack_engine/np_evaluator.py
  - engine/nervepack_engine/np_model.py
  - engine/setup/model-inventory.json
  - engine/setup/np-dashboard-server.py
  - engine/setup/np-diff-review.py
  - engine/setup/np_agentic_cron.py
  - engine/setup/np_implement_suggestion.py
  - engine/setup/np_llm_agent.py
  - engine/setup/np_skill_maintain.py
  - engine/setup/toggle-schema.json
  - engine/setup/toggles.conf
  - engine/setup/tests/evaluator/test_dashboard_server.py
  - engine/setup/tests/evaluator/test_implement.sh
  - engine/setup/tests/evaluator/test_implement_queue.py
  - engine/setup/tests/llm/test_np_model_select.py
  - engine/setup/tests/skills/test_np_llm_agent.py
---

# 0042: Implement queue and per-feature model picker

## Context and problem statement

Implement jobs failed with a model-not-found error. The pinned model id had been
retired, and nothing surfaced it. A second click during a running job returned
"busy" and dropped the request.

## Considered options

1. Hardcode a newer id. Good, because it is small. Bad, because the next
   retirement repeats the outage.
2. Curated inventory, per-feature params, and a probe. Good, because a user can
   switch models from the dashboard and see which ones answer. Bad, because it
   adds a panel and three endpoints.

## Decision

We will resolve each model call as env var, then `models.<feature>`, then
`models.<tier>`, then the built-in default. We will ship a curated inventory and
a cached probe. We will queue implement clicks FIFO and drain them under the
existing lock.

Chosen option: "Curated inventory, per-feature params, and a probe", because it
turns a silent outage into a visible, fixable state.

## Non-goals

- Live model discovery from an API. The inventory is curated by hand.
- Parallel implement jobs. One job runs at a time.

## Cross-cutting concerns

- Security: `/api/models/select` accepts only inventory ids and known keys.
- Privacy: the probe sends a fixed prompt with no user data.
- Observability: `model_error` in the status file and the dashboard banner.

## Consequences

- Good, because a retired model shows as a banner that links to its row.
- Good, because rapid clicks queue instead of failing.
- Bad, because "Probe all" blocks the request up to 45s per model.

## Confirmation

`test_np_model_select.py`, `test_implement_queue.py`, and the new cases in
`test_dashboard_server.py` and `test_implement.sh`.

## Rollback

Revert the commit. Stale `implement-queue/` files are ignored by the old code.
Remove any `models.*` lines from `toggles.local`.

## Deviations
