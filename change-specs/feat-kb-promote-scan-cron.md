---
id: 0041
status: accepted
date: 2026-09-25
tier: high
blast_radius:
  - agents/np-flow-kb-promote-scan.md
  - agents/README.md
  - engine/setup/np_agentic_cron.py
  - engine/setup/np_scheduler_install.py
  - engine/setup/np_toggle_audit.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/nervepack_engine/cli.py
  - engine/nervepack_engine/np_maintenance_freshness.py
  - engine/setup/tests/maintain/test_np_kb_promote_scan.py
  - engine/setup/tests/maintain/test_np_maintenance_freshness.py
  - engine/setup/tests/nervepack_engine/test_np_scheduler_install.py
  - docs/ARCHITECTURE.md
  - change-specs/feat-kb-promote-scan-cron.md
---

# 0041 — Weekly kb-promote-scan cron

## Problem

data-base ships a `harness-promote-scan` skill meant to run weekly from each
teammate's local harness. Harness paths exist only on the local machine, so no
cloud routine can run it. Nothing in nervepack schedules it.

The launchd installer also dropped the weekday of weekly jobs. `refine` and
`compact` ran daily on macOS.

## Change

Add a `kb-promote-scan` agentic cron, Monday 08:45, gated by
`maintain.kb_promote_scan` (default on). Its prompt makes a fresh data-base
worktree from `origin/trunk`, runs the skill, and on new queue items runs
`pr-review`, commits, pushes, opens a PR, and watches checks. It never merges.

Emit `Weekday` in launchd plists for every weekly job.

## Alternatives rejected

- A cloud routine: it cannot see the local harness paths.
- A deterministic Python body: the skill is an agent procedure, not code.

## Verification

`test_np_kb_promote_scan.py` covers gating, prompt contract, and dispatch.
`test_np_scheduler_install.py` covers the new row and the launchd weekday.

## Rollback

1. Turn the job off with `maintain.kb_promote_scan=off`. The next run skips.
2. Remove the plist: `launchctl bootout gui/$(id -u)/com.nervepack.kb-promote-scan`,
   then delete `~/Library/LaunchAgents/com.nervepack.kb-promote-scan.plist`.
3. Revert this PR and rerun `cli.py setup install-memory-launchd` to restore the
   old plists.
