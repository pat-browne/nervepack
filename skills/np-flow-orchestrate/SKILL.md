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

1. Call `start_session` once. The brief names the ticket.
2. The brief tells the child to run the repo's plan/work entry point in its own
   worktree: [[np-flow-develop]], or the repo's own factory when it has one.
3. Paste the prime and capture blocks from `np-core-dispatch`
   references/nervepack-context.md into every brief. Each child recalls related
   nervepack context first and captures at each milestone.
4. Talk to children with the session tools (`send_message`, `get_session`,
   `list_sessions`).

## The prompt

```text
You are my orchestrator for [category of work]. No code here. Start one Claude
session per ticket. Each runs [the repo's plan/work entry point] in its own
worktree.

- Lead with what needs me, then in progress, then done.

- One decision at a time, in plain language, with your recommendation and the
  trade-off.

- I approve every plan and risky merge. Record only what I typed, then tell the
  child to continue. Never send me into a child session for something you can do.

- Check the diff, the merge gate and CI yourself. Never trust a child's summary.

- Before saying someone waits on me, read the latest PR and chat messages.

- Keep a ledger in memory (paused, waiting on me, done) so state survives
  compaction.

- Every brief tells the child to recall nervepack context before it designs,
  and to run /np-core-capture-learning at each milestone. A child is not done
  until its final report has a "Captured:" line.

- Small calls are yours, but tell me after you make them. Scope, security, or
  anything customers see comes to me.

List my tickets for this work, including ones that name me as owner in the
body, and wait for my reply.
```

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
| Done, failed or ended with no `Captured:` line | Send it one message: run /np-core-capture-learning now. A session already gone gets a Haiku agent that captures from its transcript. |

Several decisions pending? Ask the most blocking one. Keep the rest in the
ledger as `waiting on me`.

## The ledger

Keep one memory file with a row per ticket. Columns: ticket, child session,
worktree, PR, state, captured, next action.

States: `paused`, `waiting on me`, `in progress`, `done`. Update the row on every
state change. After a compaction, read the ledger before anything else.

`captured` holds the paths from the child's `Captured:` line, or `no`. A row
cannot move to `done` while it says `no`. Check it before you report a ticket
finished, and again when you close out the whole run, because a child can end
without warning.

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
