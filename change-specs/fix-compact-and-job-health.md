---
id: 0083
status: accepted
date: 2026-10-14
tier: high
blast_radius:
  - agents/np-flow-weekly-compact.md
  - engine/setup/np_compact_scan.py
  - engine/setup/tests/maintain/test_np_compact_scan.py
  - engine/nervepack_engine/np_job_health.py
  - engine/setup/tests/maintain/test_np_job_health.py
  - engine/setup/np_scheduler_install.py
  - engine/nervepack_engine/np_doctor.py
  - engine/onboard/capabilities.json
  - engine/setup/np-dashboard-server.py
  - engine/setup/tests/evaluator/test_dashboard_server.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - docs/ARCHITECTURE.md
  - change-specs/fix-compact-and-job-health.md
---

# 0083: Reachable compact thresholds and a scheduled-job health report

## Context and problem statement

The weekly compact job ran on time and reported success, but never wrote a proposal.
Its prompt asked for Jaccard of 0.4 or more and for SKILL.md files over 300 lines.
The best real pair scores 0.31.
skill-maintain keeps every SKILL.md under 8 KB, so the line cutoff never fires.

Step 1 also checked a top-level `setup/` dir that moved to `engine/setup/`.
Proposals went under the agent's working dir, the engine repo.
The dashboard reads the content overlay's `compact-proposals/`.

Separately, no single view showed whether each scheduled job is installed,
enabled, succeeding and on time.

## Considered options

1. Edit the thresholds in the prompt only. Bad, because nothing tests the numbers.
2. A deterministic scanner the prompt runs, with thresholds as toggle params.
   Good, because the numbers are tested and tunable.
3. Extend `np_maintenance_freshness` for job health. Bad, because it answers
   one question by design and keeps its own job list.

## Decision

We will add `engine/setup/np_compact_scan.py`.
It scores pairs at or above `maintain.compact_propose_min` (default 0.3).
It flags skills whose SKILL.md plus references/ exceed `maintain.compact_split_total_kb` (default 40).
It names the overlay `compact-proposals/` as the output dir.

The prompt runs the scanner and checks `engine/setup`.
It commits proposals only when the overlay checkout is on main.
The dashboard reads the file from disk either way.

We will add `engine/nervepack_engine/np_job_health.py`.
Its job list is `np_scheduler_install._JOBS` and a new `JOB_TOGGLES` map.
It also picks up extra `com.nervepack.*` launchd agents.
The doctor gets a `job-health` check. The dashboard server gets `GET /api/jobs`.
Toggle: `maintain.job_health`.

## Non-goals

- No dashboard panel. A panel can consume `/api/jobs` later.
- No change to `maintenance-freshness`.

## Cross-cutting concerns

- Security: `/api/jobs` is a GET behind the loopback Host check. It runs fixed argv lists only.
- Privacy: rows hold job names, paths and timestamps, no log content.
- Observability: this change is observability.

## Consequences

- Good, because compact proposals can now appear where the dashboard reads.
- Good, because one table shows every job on launchd, cron or schtasks.
- Bad, because the lower floor proposes pairs a human may reject. `REJECTED.md` stops repeats.

## Confirmation

`test_np_compact_scan.py`, `test_np_job_health.py`, and
`test_jobs_endpoint_lists_scheduled_jobs` in `test_dashboard_server.py`.

## Rollback

Revert the squash commit.

The scheduler change only adds the `JOB_TOGGLES` map.
Installed plists, crontab lines and tasks stay byte-identical.

To stop the new check without a revert, set `maintain.job_health` off.

## Deviations

- 2026-10-14: renamed this spec to match the branch slug that spec-guard expects.
- 2026-10-14: raised the tier to high, which the scheduler installer path forces.
