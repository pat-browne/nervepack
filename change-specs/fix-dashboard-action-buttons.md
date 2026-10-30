---
id: 0106
status: accepted
date: 2026-10-30
tier: high
blast_radius:
  - dashboard/build.py
  - dashboard/index.html
  - engine/nervepack_engine/np_dashboard.py
  - engine/nervepack_engine/np_doctor.py
  - engine/nervepack_engine/np_scrub.py
  - engine/onboard/capabilities.json
  - engine/setup/np-dashboard-server.py
  - engine/setup/np_dashboard_actions.py
  - engine/setup/np_implement_suggestion.py
  - engine/setup/tests/e2e/**
  - engine/setup/tests/evaluator/**
  - .github/workflows/ci.yml
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - change-specs/fix-dashboard-action-buttons.md
---

# 0106: One hardened path for every dashboard action button

## Context and problem statement

The Graduate, Apply and Implement buttons broke again and again. Each fix patched
one symptom. A click could do nothing, say Done when nothing landed, or fail with
no message. Four root causes sat under those symptoms.

1. The server ignored SIGCHLD to avoid zombies. The kernel then reaped every child,
   so each `subprocess.run` in the server reported exit code 0. A preflight git
   check passed on a folder that was not a repository.

2. A job that failed to push still wrote Done. A rebase race or a stale overlay
   checkout produced a false success, and the entry stayed on the page.

3. The page read the local overlay checkout while jobs landed on origin. Handled
   entries reappeared as stale rows.

4. A long-lived server kept old routes. A server from before the fingerprint
   field reported no pid and was never restarted.

## Considered options

1. Patch each button again. Bad, because the same classes recur.

2. One shared action path with preflight, structured errors and a self-check.
   Good, because every button gets the same fix once.

## Decision

We will route every job button through `start_job()` in the dashboard server.
It runs a preflight, dedupes, spawns with the job log kept, and returns
`{ok, error, code, hint}` on any failure. The server reaps its own children with
a thread per job and no longer ignores SIGCHLD. A landing that fails is a failed job.

Applied entries get a per-machine marker so the page hides them. The page shows
every failure on the row and in a banner, never a native dialog. A `/api/doctor`
route, a startup log line, and a `dashboard-actions` doctor capability name a broken
action before a click. The launcher restarts a legacy server that reports no pid.

Chosen option: "one shared action path".

## Non-goals

Changing which agent prompts the jobs run, or the compact and graduate semantics.

## Cross-cutting concerns

- Security: routes keep the loopback bind and the CSRF header. Lesson names pass an
  allowlist before they build a path. The launcher signals a pid only after the
  existing listener, uid and command checks.
- Privacy: job output goes to a local cache log only. `redact()` strips URL
  credentials and token-shaped strings from every self-check row, HTTP error body
  and status-file reason, and caps their length.
- Observability: `dashboard-jobs.log`, the server log, `/api/doctor`, and the banner.

## Consequences

- Good, because a failed click now says why and where to look.
- Bad, because the preflight adds one git call per click.
- Neutral, because the stub job seam skips the overlay checks, as before.

## Confirmation

`engine/setup/tests/evaluator/test_dashboard_action_errors.py` covers each
endpoint and failure. `engine/setup/tests/e2e/test_action_buttons_flow.py` clicks
every button in a browser against a fixture overlay. The `dashboard-actions` doctor
check and `GET /api/doctor` report the live state.

## Rollback

Revert the PR. The CI change only adds one module to the informational e2e job.
Applied markers live in `~/.cache/nervepack` and need no cleanup.

## Deviations
