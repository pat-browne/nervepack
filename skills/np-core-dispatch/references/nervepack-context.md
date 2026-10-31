# Prime and capture: the two blocks every brief carries

A fresh agent starts with no nervepack context. Nothing tells it to save what
it learns either. Paste both blocks into every brief sent by
[[np-core-dispatch]], [[np-flow-orchestrate]], [[np-flow-speed]] or
`np-flow-develop`.

The lead does not run them. The worker does.

## Prime block (first 2 minutes, before reading code)

```text
Before you design or edit, load related nervepack context. Budget: 6 tool
calls, then move on.
1. Recall: call the nervepack_recall MCP tool with 3-6 keywords from the
   task (kinds: episodic, lesson). No MCP tool? Run /np-core-recall <keywords>.
2. Skills: grep INDEX.md in ~/Code/nervepack and the content overlay for the
   same keywords. Invoke only a skill whose description matches the task.
3. Wiki: for each tech stack the task touches, read its synthesis page,
   wiki/topics/<stack>/<stack>.md, if one exists. nervepack_recall does not
   search the wiki, so grep wiki/ and memory/stack-facts/ in the content overlay.
4. Read at most 3 hits besides the wiki page. A hit that conflicts with the
   repo's CLAUDE.md loses.
5. Start your first report line with "Nervepack context:" and name what you
   loaded, or "none found".
```

The budget keeps priming cheap. Three hits catch a prior decision or a known
trap. Reading the whole wiki costs more than it saves.

Take keywords from the ticket text, the repo name, and the tool or API
involved. Do not paste a lesson into the brief. The worker's own recall is
current, and yours is a stale copy.

## Capture block (milestones, not just the end)

```text
Capture as you go with /np-core-capture-learning. Run it at each of these:
- the plan is approved or settled
- a failure taught you something (root cause found, wrong assumption fixed)
- the PR opens, and again when it merges or deploys
- the task is done, blocked, or about to be handed back

Each run covers only what is new since the last.

Before the final report, run the stack sweep. See np-core-capture-learning,
references/stack-wiki.md. Name each tech stack you touched and the facts you
verified about it. Write them to the wiki only if a human is attending this
session. A dispatched worker or child session is unattended: list the facts
under "Stack facts:" in the report and leave the wiki write to the lead or a
human. The capture hook stages them in memory/stack-facts/ either way.

End your final report with "Captured: <paths>", wiki pages included, or
"Captured: nothing new, because <reason>".
```

A session can end with no warning: a closed window, a crash, a watchdog
stall, `/exit`. Anything captured at a milestone survives. Anything held for
"the end" does not.

## What backs this up when a session dies

| Layer | Covers | Gap |
|---|---|---|
| Milestone capture (above) | Deliberate learnings, saved while the agent is alive | Only what the agent chose to save |
| SessionEnd `episodic-capture` + `session-flush` | Narrative of the session | Best-effort. `/exit` fires no SessionEnd, and slow hooks get killed |
| SessionStart `backcapture-sweep` | Re-captures the previous session from its on-disk transcript | Runs at the next session start, and only for sessions with their own transcript |
| Capture hook `stack_facts[]`, then `episodic-maintain` §5c | Stack facts from any session, staged in `memory/stack-facts/` | Not in the wiki until a human promotes them |
| `post-ship-capture` hook | Prompts a capture after a merge or deploy command | Fires only on a matching Bash command |

## Subagents and child sessions

The sweep never sees a subagent started with the Agent tool. It has no
session of its own, so the parent owns its capture.

Treat a missing `Captured:` line in a subagent's report as unfinished work.
Run the capture from the parent. Or dispatch a Haiku agent with the report
and ask it to capture.

A session started with `start_session` is a full session, so the sweep covers
it. A dead child with no `Captured:` line still gets a coordinator check. See
the ledger rules in [[np-flow-orchestrate]].
