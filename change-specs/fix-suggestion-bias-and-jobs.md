---
id: 0119
status: accepted
date: 2026-11-19
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/security_recall.py
  - engine/nervepack_engine/np_evaluator.py
  - engine/nervepack_engine/np_job_health.py
  - engine/setup/np-suggestions-review.py
  - engine/setup/np_git_publish.py
  - engine/setup/np_implement_suggestion.py
  - engine/setup/tests/**
  - dashboard/build.py
  - dashboard/index.html
  - docs/ARCHITECTURE.md
  - change-specs/**
---

# 0119: Unbias evaluator suggestions and fix job health

## Context and problem statement

2,781 of 8,431 evaluator suggestions (33%) were "invoke security-review"
reminders. The security hook fired on any prompt with the word "security".
The judge then logged the unused skill as a miss.

The judge saw only a skill count, so it could not name a content file to
change. Ranking sorted by the model's own confidence. Paraphrases never merged.

Six scheduled jobs failed on an account refusal. The health check called one
of them "ok" and "16d overdue". The refusal text matched no error pattern, and
the log had no run header.

## Considered options

1. Delete the security hook. Bad, because a real review request still
   benefits from the reminder.
2. Fix each cause separately. Good, because each fix is small and tested.

## Decision

We will match review intent in the security hook. We will pass an asset index
to the judge, with new targets and an `asset` field.

Keyword-hook nudges stop counting as misses. Suggestions cluster by token
overlap and rank by confidence times recurrence.

Job health treats usage-limit refusals as errors. Last run is the later of
stamp and mtime. A rejected push rebases and retries once on a clean checkout.

The dashboard shows health checks under the wiki list. Chosen option: 2.

## Non-goals

Restoring the scheduled token's usage allocation. That is an account action.
Resolving the old backlog of "invoke skill" suggestions.

## Cross-cutting concerns

- Security: the hook fires less often. A request with no review verb or
  vulnerability term gets no reminder.
- Privacy: the asset index holds file and skill names only, no content.
- Observability: job health now reports refusals that read "ok" before.

## Consequences

- Good, because the board shows themes, ranked by recurrence.
- Bad, because the judge prompt grows by up to 12 KB.
- Neutral, because old metrics records keep their old targets.

## Confirmation

The suite passes: `bash engine/setup/tests/run-all.sh`. Named tests:
`test_security_recall`, `test_evaluator_asset_scope`,
`test_suggestions_review`, `test_np_job_health`, `test_np_git_publish` and
`test_dashboard_jobs_panel`.

## Rollback

Revert the squash commit on `main` with `git revert`. No data migrates.
Records in `metrics.jsonl` work under the old code. The resolved ledger is
append-only.

## Deviations
