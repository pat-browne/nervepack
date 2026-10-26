---
name: np-flow-orchestrate
description: 'Use when several tickets of one kind of work should run at once, each in its own session and worktree, with one coordinator driving them. Triggers: "orchestrate my tickets", "run these tickets in parallel", "be my orchestrator", "/np-orchestrate".'
---

# np-flow-orchestrate

One coordinator session drives many tickets and writes no code. Each ticket gets
its own child session and worktree, running the repo's dev flow. The user plans
inside each child. The coordinator runs the loop and pings the user only when
needed.

Announce: "Using np-flow-orchestrate."

## Setup (desktop app)

1. Start the coordinator in a worktree session.
2. Paste the prompt below, with the category of work filled in.
3. The coordinator lists the user's tickets and waits for a reply.

Then, for each chosen ticket:

1. Call `start_session` once, with a model. The brief names the ticket.
2. The brief tells the child to run the repo's plan/work entry point in its own
   worktree: [[np-flow-develop]], or the repo's own factory when it has one.
3. Talk to children with the session tools (`send_message`, `get_session`,
   `list_sessions`).

## The prompt

```text
You are my orchestrator for [category of work]. No code here. Start one Claude
session per ticket. Each runs [the repo's plan/work entry point] in its own
worktree.

- Never let a session inherit your model. Pass the cheapest model that fits on
  every start. Hard calls come back to you as decision requests.

- Lead with what needs me, then in progress, then done.

- One decision at a time, in plain language, with your recommendation and the
  trade-off.

- I approve every plan and risky merge. Record only what I typed, then tell the
  child to continue. Never send me into a child session for something you can do.

- Check the diff, the merge gate and CI yourself. Never trust a child's summary.

- Before saying someone waits on me, read the latest PR and chat messages.

- Keep a ledger in memory (paused, waiting on me, done) so state survives
  compaction.

- Small calls are yours, but tell me after you make them. Scope, security, or
  anything customers see comes to me.

List my tickets for this work, including ones that name me as owner in the
body, and wait for my reply.
```

## Worker models

The coordinator is top tier. It plans and decides, and does no worker task
itself. This section owns the rule for every coordinator, including
[[np-flow-speed]] and [[np-core-dispatch]].

- Never let a worker inherit your model. Set one on every subagent and every
  separate session you start.
- Pick the cheapest model that fits: Haiku for lookups and mechanical steps,
  Sonnet for implementation, research and review. The table is in
  [[np-flow-speed]].
- When the host's session-start tool takes a model argument, always pass it.
  An omitted argument inherits yours. If the tool offers no model argument, as
  with a forked session, start a fresh session or a subagent that takes one.
- Ticket children plan and implement, so start them on Sonnet unless the user
  names another model.
- A worker sends a hard call back as a decision request: the options and its
  pick. You decide, tell the worker, and record the call in the ledger.

## Close-out: capture, then archive

This section owns the rule for every coordinator, including [[np-core-dispatch]]
and [[np-flow-speed]]. A child that met its stated goal and sits idle gets closed
out, never left open.

1. Confirm the goal is met from evidence: merged PR, pushed commit, or report
   verified. A child still owed a step (live checks, a merge, an answer) stays
   open.
2. Send it [[np-core-capture-learning]] as one message. Tell it to take no new
   work after the capture.
3. Wait for its capture report. Check where the capture landed: a commit, a
   branch, or memory.
4. Run `git -C <child worktree> status -sb`. Archive only when the tree is clean
   and the branch is not ahead of its remote.
5. Archive the child. Mark its row in § The ledger `done`, with the PR if one
   exists and the capture location.

A child that ends its turn on a gate or a question, with no capture report,
stays open as `waiting on me`. Archiving can remove the child's folder. Never
archive a child whose folder another live session uses.

## The loop

Bring these to the user:

| Child reports | Coordinator does |
|---|---|
| Plan ready | Summarize it with a recommendation. Relay only the user's words back. |
| Scope, security or customer-facing question | Queue it as one decision. |
| Risky merge | Ask for approval after your own checks. |

Handle these yourself:

| Child reports | Coordinator does |
|---|---|
| "Ready to merge" | Read the diff, the merge gate and CI yourself. |
| Small technical call | Decide, tell the child, list it in the next update. |
| Stuck or silent | Read its transcript and PR before you call it blocked. |

Several decisions pending? Ask the most blocking one. Keep the rest in the
ledger as `waiting on me`.

## The ledger

Keep one memory file with a row per ticket. Columns: ticket, child session,
worktree, PR, state, next action.

States: `paused`, `waiting on me`, `in progress`, `done`. Update the row on every
state change. After a compaction, read the ledger before anything else.

## Every update to the user

1. Needs you: one decision, recommendation, trade-off.
2. In progress: one line per ticket.
3. Done: ticket, PR, merge state.
4. Calls I made: one line each, with the reason.

Form follows [[np-flow-concise-output]].

## What this is not

- Not [[np-core-dispatch]]. Dispatch hands one task to one agent. This runs a
  fleet of user-planned tickets.
- Not [[np-flow-speed]]. Speed mode removes check-ins for one deliverable. The
  orchestrator keeps the user on every plan and risky merge.

- Not a coding session. A coordinator that edits code has stopped coordinating.
- Not a way past the repo's `CLAUDE.md`. Deploy rules still bind every child.
