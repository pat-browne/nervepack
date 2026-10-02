---
id: 0044
status: accepted
date: 2026-10-02
tier: normal
blast_radius:
  - engine/setup/np-dashboard-server.py
  - engine/nervepack_engine/np_model.py
  - dashboard/index.html
  - engine/setup/tests/evaluator/test_dashboard_server.py
  - engine/setup/tests/llm/test_np_model_select.py
  - docs/ARCHITECTURE.md
  - change-specs/feat-async-model-probe.md
---

# 0044: Run the model probe as a detached job

## Context and problem statement

POST /api/models/probe probed every inventory model in turn inside the request.
Each probe has a 45s timeout, so "Probe all" held the dashboard for minutes.

## Considered options

1. Probe in a server thread. Good, because no new process. Bad, because state
   lives in server memory and a server restart loses it.
2. Spawn a detached job, the /api/implement pattern. Good, because the request
   returns at once and the job writes the existing probe cache. Bad, because it
   needs an in-progress marker on disk.

## Decision

We will spawn `np_model.py probe <models...>` detached (start_new_session, stdin
DEVNULL, np_bashlib.argv). The server claims `model-probe.json.running` with
O_EXCL before the spawn. The job clears it when done. GET /api/models reports
`probe_running`. A second request while a run holds the marker returns
`{ok, started: false, running: true}`. A marker older than its run budget
(timeout x models + 60s) counts as stale.

Chosen option: "detached job", because it matches /api/implement and survives a
server restart.

## Non-goals

Per-model progress reporting. The cache already updates per model.

## Cross-cutting concerns

- Security: argv list, no shell. Model ids are checked against the inventory.
- Privacy: none.
- Observability: `probe_running` in GET /api/models. Results in model-probe.json.

## Consequences

- Good, because the dashboard never blocks on a probe.
- Neutral, because the UI polls GET /api/models every 3s while a probe runs.

## Confirmation

`test_models_probe_one_model`, `test_models_probe_while_running_is_noop`, and
`ProbeMarkerTest` in the regression suite.

## Rollback

Revert the squash commit.

## Deviations
