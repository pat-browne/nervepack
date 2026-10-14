---
id: 0079
status: accepted
date: 2026-10-14
tier: normal
blast_radius:
  - engine/setup/np-dashboard-server.py
  - engine/setup/np_dashboard_actions.py
  - engine/nervepack_engine/np_dashboard.py
  - engine/setup/tests/evaluator/test_*dashboard*.py
  - dashboard/index.html
  - change-specs/fix-dashboard-implement-routes.md
---

# 0079: Restart a stale dashboard server

## Context and problem statement

The dashboard server is long-lived. It reads index.html on every request.
It keeps the routes it loaded at start.

After an update adds routes, new buttons get "no such route". The launcher
only checks that the port listens, so it never replaces the old process.

## Considered options

1. Fingerprint the route code and restart on mismatch. Good, because it heals
   on the next dashboard open.
2. Document a manual restart. Bad, because every route change repeats the bug.

## Decision

We will report a route-code fingerprint and the pid from /api/health.
dashboard_url() stops a server whose fingerprint differs, then spawns a fresh one.
Compact Apply uses the primary button class.

Chosen option: "Fingerprint and restart", because it fixes the class of bug.

## Non-goals

Restarting a server too old to report its pid. That one needs one manual kill.

## Cross-cutting concerns

- Security: the kill targets only the pid the loopback server reports, and only when it is a real pid (>1, not a bool) in an `ok: true` health reply.
- Privacy: none.
- Observability: /api/health now shows pid and code.

## Consequences

- Good, because new routes work after an update without a manual restart.
- Neutral, because each dashboard open makes one extra loopback GET.

## Confirmation

test_np_dashboard.TestStaleServerRestart and
test_dashboard_server.test_health_reports_code_fingerprint_and_pid.

## Rollback

Revert the PR.

## Deviations

- 2026-10-14: renamed the spec to the slug spec-guard expects (fix-dashboard-...). No new code paths.
