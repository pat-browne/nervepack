---
id: 0098
status: accepted
date: 2026-10-25
tier: high
blast_radius:
  - engine/nervepack_engine/np_claims.py
  - engine/nervepack_engine/hooks/claim_hook.py
  - engine/nervepack_engine/cli.py
  - engine/setup/toggles.conf
  - engine/setup/hooks.manifest
  - engine/setup/toggle-schema.json
  - engine/setup/tests/**
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - skills/np-flow-merge-gate/SKILL.md
  - change-specs/**
---

# 0098: session claims, so concurrent agents in one repo see each other

## Context and problem statement

Two nervepack sessions in one repo, each in its own worktree, cannot see each other. The resume pointer holds one slot and describes a prior session, never a live one. The SDD ledger lives inside a worktree, and `np-flow-merge-gate` acts only at merge time. So the second agent in learns about the first at the merge, when the conflict already exists.

The design is in the content overlay, `docs/superpowers/specs/2026-10-25-concurrent-agent-claims-design.md`.

## Considered options

1. The progress file as the marker. Bad: it appears at Phase 5, lives inside the worktree, and has one writer.
2. One claim file per session in the shared git common dir. Good: every worktree sees it, there is no write contention, and it exists from the first prompt. Neutral: it is local to one machine.
3. A hard lock that blocks a second session. Bad: a claim cannot tell a human from a stuck agent, and a wrong block bricks a session.

## Decision

We will write one JSON claim per session under the repo's git common dir, in `nervepack/claims/<session_id>.json`, on every UserPromptSubmit in a git repo. We release it on SessionEnd. We surface the other live claims once per session with the reader's FIFO rank and duty. A `claim` CLI lets the develop flow add intent, paths and phase. Overlap informs, never blocks.

Chosen option: "one claim file per session", because it needs no new daemon, no new lock, and rides the existing hook call sites.

## Non-goals

- Cross-machine claims. `merge-wait` on `origin/main` covers that case.
- Blocking. A claim-guard is a possible later hook under invariant 1.
- Changing the progress file or the resume pointer's schema.

## Cross-cutting concerns

- Security: the claim holds a path, a branch, a pid and a free-text intent. No secrets. It never leaves the machine and is never committed.
- Privacy: the intent is user-typed. No scrub, since the file is local and short-lived.
- Observability: `cli.py claim list` shows every live claim. Bails log to `~/.cache/nervepack/claims.log`.

## Consequences

- Good: a follower learns its duty before it branches.
- Bad: every prompt costs three git calls, throttled to one write per 60 seconds per session.
- Neutral: a claim whose session died without SessionEnd lingers up to `claims.stale_days` (7). Pid is recorded but never used to prune, since a hook's parent pid is a transient shell.

## Confirmation

The tests `test_np_claims.py` and `test_claim_hook.py` under `engine/setup/tests/nervepack_engine/` cover write, heartbeat, release, FIFO rank, overlap, stale pruning, same-worktree stop, fail-open on a non-git cwd, and toggle off. `test_cli.py` covers the `claim` subcommand.

## Rollback

`cli.py toggle claims off` silences both hooks and the CLI at once. A full revert is `git revert` of the squash commit, then `cli.py setup install-hooks` to drop the two manifest rows. Claim files under `.git/nervepack/claims/` are inert data and can be deleted by hand.

## Deviations

- 2026-10-25: added `engine/setup/toggle-schema.json`. The dashboard settings test requires a description for every toggle and param, so the new `claims` family needs entries there.
