---
id: 0123
status: accepted
date: 2026-11-20
tier: high
blast_radius:
  - engine/setup/np_git_publish.py
  - engine/setup/np_aggregate.py
  - engine/setup/np_agentic_cron.py
  - agents/np-flow-memory-promote.md
  - agents/np-flow-scheduled-refine.md
  - agents/np-flow-weekly-compact.md
  - agents/np-flow-episodic-maintain.md
  - engine/setup/tests/evaluator/test_np_git_publish_sync.py
  - engine/setup/tests/evaluator/test_np_git_publish.py
  - docs/ARCHITECTURE.md
  - CHANGELOG.md
  - change-specs/fix-content-sync-push.md
---

# 0123: Cron pushes sync with origin first

## Context and problem statement

Crons commit to the content overlay, then push. Once origin moved, every push
was rejected as non-fast-forward. The old retry ran `pull --rebase`, which
conflicted on `metrics.jsonl` and `metrics.js` and gave up. On 2026-11-20, 31
commits sat unpushed in nervepack-content since 2026-11-18. Agentic crons ran
a bare `git push` from their prompts with no retry at all.

## Considered options

1. One helper in `np_git_publish` that fetches, rebases with a resolver, then
   pushes. Good, because every job already calls `publish()`.
2. A `merge=union` gitattribute in the content repo. Bad, because it does not
   rebuild `metrics.js` and needs a change in every overlay.
3. Merge instead of rebase. Bad, because it adds a merge commit per cron run.

## Decision

`sync_push()` fetches origin, and when HEAD is behind it rebases on a clean
tree. It unions conflicting `*.jsonl` files and takes origin's copy of
generated files, then rebuilds `dashboard/data/metrics.js` and commits it. Any
other conflict aborts the rebase, logs one line, and returns failure with the
commits kept local. It never force-pushes. `_push()` and so `publish()` and
`push_to_main()` route through it. Agent prompts call
`np_git_publish.py push <repo>`. `np_agentic_cron.py` publishes any commit
an agent left unpushed.

## Non-goals

`np_implement_suggestion.py` keeps its own replay and push logic. The sync tool
stays fast-forward only.

## Cross-cutting concerns

A dirty tree behind origin still refuses, as before. The skill-maintain and
aggregate status lines now carry the conflict path instead of `push rejected`.

## Rollback

Revert the merge commit. Crons fall back to a single push with a
`pull --rebase` retry. Commits stranded by a conflict stay on the local branch,
so nothing is lost either way.
