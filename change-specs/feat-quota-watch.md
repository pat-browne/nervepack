---
id: 0097
status: accepted
date: 2026-10-25
tier: high
blast_radius:
  - .claude-plugin/plugin.json
  - INDEX.md
  - agents/README.md
  - engine/nervepack_engine/cli.py
  - engine/nervepack_engine/hooks/quota_detect.py
  - engine/nervepack_engine/hooks/quota_notify.py
  - engine/nervepack_engine/np_quota_watch.py
  - engine/setup/hooks.manifest
  - engine/setup/np_bootstrap.py
  - engine/setup/np_scheduler_install.py
  - engine/setup/toggles.conf
  - engine/setup/tests/nervepack_engine/test_np_quota_watch.py
  - skills/np-flow-quota-watch/SKILL.md
  - change-specs/feat-quota-watch.md
---

# 0097: Quota-watch resume nudge

## Context and problem statement

A session that hits the claude.ai usage limit stops. Nothing tells the user when the limit resets. They return late or poll by hand, and unattended work stays idle.

## Considered options

1. Stop hook plus a 30-minute cron, no model call — Good, because it costs no tokens and fails open. Bad, because the nudge can lag the reset by up to the cron interval minus the 60 second delay.
2. A long-running sleeper process per session — Good, because the timing is exact. Bad, because it needs lifecycle management and dies with the session.
3. Do nothing — Good, because it adds no code. Bad, because the idle time stays.

## Decision

We will detect a usage-limit message in a Stop hook and record the reset time. A cron scan then sends one notification a set delay after the reset, so the user can type "continue".

Chosen option: "Stop hook plus a 30-minute cron", because it needs no model call and no long-lived process.

## Non-goals

Resuming the session automatically. The user decides whether to continue, and a headless resume could act without review.

## Cross-cutting concerns

- Security: the hook reads only the session's own last message. It stores a timestamp and a session id.
- Privacy: no message text is stored beyond the reset time string.
- Observability: the cron logs each scan and each notification sent.

## Consequences

- Good, because a limit hit no longer goes unnoticed.
- Bad, because the cron adds one more scheduled job to install and diagnose.
- Neutral, because the `quota_watch` toggle turns the whole feature off.

## Confirmation

`test_np_quota_watch.py` covers detection, scheduling and notification. `cli.py doctor` reports the cron once installed.

## Rollback

Set `quota_watch` off with `cli.py toggle`. The detect and notify steps then do nothing.

To remove the code, revert the merge commit of this PR. Then delete the crontab line marked `nervepack-quota-watch` with `crontab -e`.

## Deviations

2026-10-25: this branch also carries a merge of `origin/main`. The merge touched `INDEX.md`, `agents/README.md`, `engine/nervepack_engine/cli.py` and `engine/setup/toggles.conf` to keep both sides. All four are already in the blast radius.
