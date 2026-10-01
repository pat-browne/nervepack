# Worktree isolation — full recipes

Read on demand from the skill body's pointer.

## Why worktrees prevent staged-work sweeps

A concurrent auto-committing cron (nervepack's own metrics/maintain crons) can
**sweep the agent's staged work** into its own commit — a `git commit -am` or
bare `git commit` against the shared index captures whatever another agent has
staged. A worktree off the committed base is immune: each worktree has its own
index, so a cron committing in the primary checkout can't touch what the agent
staged in its worktree.

Two agents editing the **same files** in parallel land on separate branches instead
of colliding. Resolve the overlap by **combining** both, not picking a side. After
the agent reports, verify on its branch (tree clean, tests green, nothing on
`main`), then merge — FF or cherry-pick — keeping the agent off `main`.

## Trust git ground truth, not the agent's report

Even when told to work in a given worktree, a dispatched agent may edit the *main*
checkout or commit to `main`/an off-branch orphan while reporting "DONE, committed"
with a plausible SHA. After each agent, confirm where the change actually landed:

```
git log --oneline
git show <sha> --stat
git merge-base --is-ancestor <sha> HEAD
```

Never accept the self-reported location. Wrong place? Use the wrong-checkout
reconcile recipe in references/recovery.md.

## Sharing one worktree safely (when isolation: "worktree" is impractical)

Give each agent an explicit, non-overlapping set of files. Forbid `git add` inside
each agent's task — the supervisor commits by exact pathspec after each task
reports back.

Put every cross-task contract (JSON shapes, type names, function signatures) in
the plan up front so agents can build to the interface without seeing each other's
in-progress edits.

Never let an agent stage tool-generated noise (`analysis_options.yaml`, `*.xcconfig`,
pbxproj, workspace files) — these appear in any dirty tree and will pollute an
unguarded commit.

**Also:** when another agent runs subagent-driven work here, the shared `.git/sdd/`
state files (`progress.md`, `task-N-brief.md`) collide — use uniquely-named
ledger/brief files, never mass-write the shared ones. See [[np-flow-merge-gate]].

Verified 2026-09-28: four agents built the Spinjam ride modeler in one worktree
simultaneously with no collisions using these rules.
