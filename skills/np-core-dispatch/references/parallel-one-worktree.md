# Several build agents in one worktree at once

Applied 2026-09-28 on a seven-task plan: four agents built in the same worktree in parallel, then two more, with no collision. Four rules made it work.

## 1. Disjoint file lists, named in the brief

Each agent gets the exact files it may create or edit, and a list of the files the other agents own. An agent that needs a file it does not own writes to a contract instead (rule 2) and reports the gap.

## 2. Cross-task contracts live in the plan

Every shape two tasks share is written down before dispatch: JSON schemas, type and field names, function signatures, the resolver order. Agents build to the contract blind. Put the contracts in a "Contracts" section of the plan, and quote the relevant lines into each brief.

## 3. Agents never stage or commit

`git add` and `git commit` are forbidden in every brief. The supervisor commits each task afterwards by exact pathspec, one commit per task, once the agent's report and the test run agree. Concurrent commits race the index lock, and a bare `commit` sweeps another agent's half-written files.

## 4. Tool noise is never staged

A parallel Flutter run rewrites `analysis_options.yaml` and the iOS `*.xcconfig` files, and `terraform init` rewrites `.terraform.lock.hcl`. Restore them with `git checkout --` before the final push. A dirty tree of this kind is not an agent's work.

## Two things this surfaced

- A second implementation of the same rules is a test of the first. The Python port of the Dart priors found a crash on short songs that the Dart tests had missed.
- When one agent's brief changes a shared number after another agent copied it, the supervisor owns the reconciliation. Grep both sides for the old value before the merge.

## When to prefer separate worktrees instead

Two agents that must touch the same file, or a task whose scope cannot be bounded to a file list, get `isolation: "worktree"` as the skill body says. One worktree is for tasks that are independent by construction.
