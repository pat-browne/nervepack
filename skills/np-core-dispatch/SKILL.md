---
name: np-core-dispatch
description: Send a task or a handoff to a fresh agent and supervise it. Use when you want another agent to carry out work — executing a [[np-core-handoff]] doc, running a long/risky job, or parallelizing — especially when you tried to "continue" a previously spawned agent and the SendMessage capability isn't available in this environment. Covers the spawn-fresh-with-context fallback, scoping, stop-points, and verification. The dispatch half of the continuity pair with [[np-core-handoff]] (handoff writes the doc; dispatch sends it).
---

# dispatch — send work to a fresh agent

`[[np-core-handoff]]` writes the doc that lets a context-free agent continue. **This
skill sends it.** Use it whenever the next move is "have an agent go do this."

## The SendMessage gotcha (why this skill exists)

Some harnesses expose a way to *continue a specific previously-spawned agent* (often
called `SendMessage`, keyed by an agent id). **It is frequently NOT available** — the
spawned agent returns an id, but no tool to message it back exists in the session.
When that happens, do **not** get stuck trying to reach the warm agent.

**Fallback (always works): spawn a FRESH agent with the full context.** For
self-contained work, a fresh agent that reads the handoff doc (or is handed the same
brief inline) is equivalent to continuing the original — it just rebuilds context from
the doc instead of memory. Point it at the handoff path and let it go. Don't block on
a continuation channel that isn't there.

## How to dispatch well

1. **Hand it a handoff, not a vibe.** Either pass a `[[np-core-handoff]]` doc path or
   inline an equivalent brief: objective, state (done/in-flight/blocked), the next
   concrete step, suggested skills, and references by path. Self-contained = succeeds.
2. **Scope it.** Say exactly what to do and what NOT to do. For multi-step work, name a
   **stop-point**: "execute steps 1–5, then STOP and report before the irreversible
   step 6." A clear stop-point is how you keep a risky run reviewable.
3. **Carry the conventions in the prompt** (a fresh agent doesn't inherit them):
   sync first (`[[np-core-sync]]`), explicit-path `git add` (never `-A`), author as
   the repo's configured git identity (never a bot) with **no LLM-attribution trailer**, validate-don't-assume, redact secrets
   (pull fresh via [[np-env-secrets-refresh]] — never inline them). Tell it to STOP and
   report on a dirty/diverged tree rather than force anything.
4. **Pick the lane.** Foreground when you want to review + relay the result this turn;
   background for long autonomous jobs that should notify on completion. Use a capable
   model for risky/judgment-heavy runs.
5. **Verify the result yourself.** Treat the agent's report as a claim — independently
   re-check the key invariants (tree clean, tests/doctor green, nothing pushed public)
   before you trust "done."

## When a dispatched agent stalls — salvage, don't re-dispatch

A backgrounded agent can come to rest with an error — a watchdog stall ("no progress
for ~600s") — **before it commits**. Re-dispatching risks another stall and throws away
work it already did. Instead:

1. **Inspect its worktree** (`git -C <worktree> status` / `diff <base>`). A stalled agent
   usually has the implementation done but **uncommitted** — it typically dies during the
   final verify step, not mid-edit.
2. If the diff is sound, **finish it yourself**: commit it, add what it didn't reach
   (docs, a missing test), verify (suite + freshness), and integrate. Salvage beats restart.
3. Re-dispatch only if the worktree is empty or the work is unsound.

**A subagent's claim about a *review* is not a verdict.** An implementer can come to rest
narrating "the review passed" — it can't see the reviewer you dispatched separately. Act
only on the reviewer's actual report or your own controller-side diff review. A
**read-only** reviewer orphaned by a session exit wrote nothing — safe to abandon; just
confirm its target work landed another way. When another agent also runs subagent-driven
work here, the shared `.git/sdd/` state files (`progress.md`, `task-N-brief.md`) collide —
use uniquely-named ledger/brief files, never mass-write the shared ones. See
[[np-flow-merge-gate]].

## Isolate with a worktree when the tree is shared

Dispatch repo-editing agents with **`isolation: "worktree"`** whenever an auto-committing
cron or another session may be active in that tree (nervepack's own metrics/maintain crons
are). Two payoffs:

- A concurrent committer can otherwise **sweep the agent's staged work** into its own
  commit (and push it). A worktree off the committed base is immune.
- Two agents editing the **same files** in parallel won't collide — each lands on its own
  branch. Expect to resolve the overlap by **combining** both, not picking a side.

After it reports, verify on its branch (tree clean, tests green, nothing on `main`), then
you merge — FF or cherry-pick — keeping the agent off `main`. See [[using-git-worktrees]].

**Trust git ground truth, not the agent's report — it can edit the wrong checkout.** Even
when told to work in a given worktree, a dispatched agent may edit the *main* checkout and
commit to `main` (or to an off-branch orphan) while still reporting "DONE, committed" with a
plausible SHA. After each agent, confirm the *actual* HEAD/branch and which commit really
contains the change (`git log --oneline`, `git show <sha> --stat`, `git merge-base
--is-ancestor <sha> HEAD`) — never accept the agent's self-reported location, and beware
self-amending on review (the controller owns that). When it landed in the wrong place,
reconcile rather than re-run: `git tag` a backup, `cherry-pick` the change onto the correct
branch, confirm content identity (`git diff <orphan> <cherry-pick>` empty), then
`git reset --hard origin/main` the polluted checkout. Pin the worktree path emphatically in
the dispatch and have the agent echo `git rev-parse --show-toplevel` before its first edit.

## Verify the whole plan, not just each task

Green per-task reviews don't mean the plan is done. A task can be silently **skipped**
when an earlier commit made a superficial one-line touch to the file it was meant to
substantively change — a false "done" no per-task review catches, since each sees only
its own diff. The net is a **whole-branch review**: one fresh, most-capable-model pass
over the full diff *against the spec*, told to hunt the missing consumer / unwired
write-path — not just critique what changed. This once caught a skipped write-path
migration (an agent's one-line stat edit made the file look handled) that would have
silently broken the feature on the next cron run. Never skip it, even when every task
came back clean.

## Not this

- A persistent message bus or agent-to-agent chat — this is one-shot dispatch +
  supervise, not a protocol.
- A replacement for doing small work inline. Dispatch when the work is large, risky,
  parallel, or genuinely better in a fresh context — not to avoid a two-line edit.
