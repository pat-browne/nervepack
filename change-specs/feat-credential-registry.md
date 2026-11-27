---
id: 0121
status: accepted
date: 2026-11-20
tier: normal
blast_radius:
  - engine/nervepack_engine/np_credentials.py
  - engine/nervepack_engine/np_doctor.py
  - engine/nervepack_engine/cli.py
  - engine/setup/credentials.json
  - engine/setup/np-dashboard-server.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/onboard/capabilities.json
  - engine/setup/tests/maintain/test_np_credentials.py
  - engine/setup/tests/evaluator/test_dashboard_creds_panel.py
  - engine/setup/tests/evaluator/test_dashboard_jobs_panel.py
  - dashboard/index.html
  - docs/ARCHITECTURE.md
  - change-specs/feat-credential-registry.md
---

# 0121: Credential registry with expiry health and rotation

## Context and problem statement

A move between Claude orgs left every scheduled job on a dead token. Only the
scheduled-auth token had any expiry tracking, and it was hardcoded. ADO PATs,
GitHub PATs and az logins live in the content overlay's prose register, so
nothing warned before they lapsed.

## Considered options

1. Hardcode more checks in the doctor. Bad, because each new credential needs an engine change and engine code would name personal items.
2. A registry the layers declare, read by one generic engine module. Good, because the overlay adds sources with no engine change.

## Decision

We will add `np_credentials.py`, which merges `engine/setup/credentials.json`
with each layer's `config/credentials.json` by name. The engine default
registers the scheduled-auth token as the first source. Its status matches
`np_token_status`, so `62-install-scheduled-auth-token.sh` keeps working
unchanged. Health feeds the doctor `credentials` check, `GET /api/credentials`
and a dashboard panel. `cli.py credentials rotate` runs auto rotations and
prints the exact command for manual ones.

Chosen option: "layer-declared registry", because it keeps the engine generic.

## Non-goals

No scheduled auto-rotation cron yet. A new cron touches all three scheduler
backends, so `rotate --due` stays on demand until an auto source exists.
Reading a vault needs the vault unlocked, so a locked vault shows `unknown`.

## Cross-cutting concerns

- Security: metadata only. `expires_cmd` output is parsed as a date and dropped. File stores get a mode check.
- Privacy: personal sources live in the private overlay, never in the engine.
- Observability: doctor line, dashboard panel and `cli.py credentials --json`.

## Consequences

- Good, because a lapsing PAT warns days ahead with the fix command.
- Bad, because each `expires_cmd` runs per survey, capped at 15 seconds.
- Neutral, because the old `scheduled-auth-token` doctor row stays.

## Confirmation

`engine/setup/tests/maintain/test_np_credentials.py` covers layering, each
status, rotation, the token parity with `np_token_status` and that no secret
value reaches output. `test_dashboard_creds_panel.py` guards the panel.

## Deviations
