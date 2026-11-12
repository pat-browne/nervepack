---
id: 0118
status: accepted
date: 2026-11-05
tier: high
blast_radius:
  - agents/np-flow-kb-promote-scan.md
  - agents/README.md
  - docs/ARCHITECTURE.md
  - engine/setup/np_agentic_cron.py
  - engine/setup/toggle-schema.json
  - engine/setup/tests/maintain/test_np_kb_promote_scan.py
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/nervepack_engine/hooks/turn_gate.py
  - engine/setup/tests/nervepack_engine/test_form_gate.py
  - engine/setup/tests/nervepack_engine/test_turn_gate.py
  - engine/setup/tests/skills/test_no_personal_skill_in_engine.sh
  - engine/setup/tests/publish/test_scan.py
  - publish/np-publish-scan.py
  - publish/deny-term-hashes.txt
  - archive/MANIFEST.md
  - change-specs/fix-planner-trial-friction.md
  - change-specs/fix-kb-promote-scan-issues.md
  - change-specs/feat-kb-promote-scan-cron.md
  - change-specs/feat-kb-promote-weekday-schedule.md
  - change-specs/fix-wiki-inline-escapes.md
  - change-specs/fix-wiki-render-all-groups.md
  - engine/setup/tests/evaluator/test_dashboard_build.py
  - engine/setup/tests/journal/test_journal_resources.py
  - engine/setup/tests/nervepack_engine/test_lesson_guard.py
  - skills/np-core-contribute/references/cross-reference-convention.md
---

# 0118: kb-promote-scan files issues and names no employer

## Context and problem statement

The team KB repo's review queue moved from a queue file to GitHub Issues on 2026-10-19.
The prompt still waited for a queue diff, so every run since then stopped early.

The prompt also named an employer, its repo, base branch and CI tools.
The engine is public and must stay employer-neutral.

## Considered options

1. Rewrite the prompt to the issue flow. Good, because it matches the skill.

2. Keep the PR phases for a future queue file. Bad, because the queue is frozen.

3. Move the prompt to the content overlay. Bad, because the cron dispatch lives in the engine.

4. Read the KB repo details from local toggle params. Good, because the engine holds only the mechanism.

## Decision

We will drop the queue review, commit, PR and checks phases.
The agent runs the skill in a detached worktree of the KB repo's base branch.
It runs the KB repo's gate commands and a scope gate on every changed path.

It pushes docs to the base branch. Skill additions go to one PR without auto-merge.

The KB checkout, `owner/name`, base branch, gate commands and commit trailer come from
`maintain.kb_promote_scan.*` params in `toggles.local`. The cron skips when they are unset.

A hashed deny list in the publish scan blocks employer terms in the engine.
It stores only sha256 digests and never prints the term.

Chosen options: 1 and 4.

## Non-goals

The routing rules themselves. They live in the KB repo's skill.

Per-layer autopromote settings in the dashboard. That is a separate feature.

Git history. Old commits still hold the terms, and rewriting them needs a force-push.

## Deviations

- Widened to the prose gates and spec 0116, which named a planning plugin by its employer brand. The exemption now lives in `form_gate.exempt_globs`, set per machine.

- Widened to the publish scan, its test and the skill-name guard, to stop a repeat.

- Widened to `archive/MANIFEST.md`, whose rows named relocated employer skills.

- Widened to four older specs, three tests and one skill reference that named the employer's KB repo. Each now says `team-kb`.

## Cross-cutting concerns

- Security: the agent pushes to the KB base branch and files issues. It never force-pushes.

- Privacy: the skill de-personalizes before writing or filing. No employer value is committed.

- Observability: phase lines in `kb-promote-scan.log`. The commit body lists every path written.

## Consequences

- Good, because harness knowledge reaches the KB without a manual review step.

- Good, because the engine carries no employer name, and CI blocks a new one.

- Bad, because a wrong doc lands on the base branch before a person reads it.

- Neutral, because a forker sets five params before the job does anything.

## Rollback

Revert the squash commit. The cron then reads no params and the old prompt returns.
The local `toggles.local` params are harmless when unread.

## Confirmation

`test_np_kb_promote_scan.py` pins the prompt rules and the unconfigured skip.
`test_scan.py` proves a hashed term is caught in content and paths and never echoed.
