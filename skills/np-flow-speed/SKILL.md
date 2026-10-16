---
name: np-flow-speed
description: 'Use when the user wants a change delivered end to end with no clarifying questions or permission check-ins. Triggers: "speed mode", "/np-speed", "just ship it", "no questions", "don''t ask, just do it".'
---

# np-flow-speed

Speed mode delivers end to end without asking: brainstorm, plan, implement,
test, review, PR, merge on green. It ends with a decisions log. The hard limits
below still stop and surface.

Announce: "Using np-flow-speed."

## What changes

- No clarifying questions. Pick the most reasonable reading, log it, continue.
- No approval check-ins between phases. Spec, plan and execution choices are
  yours.
- Workers run on the cheapest model that fits. The coordinator only briefs,
  decides and verifies.
- Run the [[np-flow-develop]] phases in order. Tests stay first and the
  deterministic gate still blocks.
- Merge on green when the repo allows a merge without a human.

## Model tiering: cheapest model that fits

Speed mode delegates hands-on work to subagents. Each one runs on the cheapest
model that can do its job. The session default is never a worker's model.

| Work | Model |
|---|---|
| Search, file reads, lookups, mechanical edits, running tests, CI checks, git and PR steps | Haiku |
| Implementation, research, debugging, code review, multi-step edits | Sonnet |
| Coordination, hard calls, final verification | Coordinator (the session model) |

- Pass a model on every subagent spawn. An unset model silently inherits the coordinator's model and costs the most.
- Start each worker at its tier in the table. A worker fails when it reports it could not finish, or its output fails verification.
- A failed Haiku worker reruns once on Sonnet. A failed Sonnet worker goes to the coordinator, never to a higher-tier worker.
- Record each step-up in the decisions log.
- The coordinator does no hands-on work a worker could do.
- Briefing and supervision follow [[np-core-dispatch]]. The tier split mirrors the model selection policy in `AGENTS.md`.

## Deferring a hard call

Some calls need higher judgment, such as a costly design fork or two
conflicting specs. A worker never asks the human for these.

It sends the call to the coordinator, the top-tier model running the session,
with the options and its pick. The coordinator decides and logs it. When the
worker is the coordinator, it decides and logs it.

## Hard limits: these still stop and surface

Speed mode never overrides any of these:

1. Harness permission prompts, the sandbox, or safety rules.
2. The repo's `CLAUDE.md`, including deploy rules such as no prod deploys on
   Fridays and all environments or none.
3. Destructive or irreversible actions.
4. Credentials or secrets.
5. Messages sent on the user's behalf.
6. Anything customer-facing.

At a limit, finish all the work that does not cross it. Then stop and surface
the limit as one decision with your recommendation.

A limit is not a deferrable call. The coordinator cannot approve it either.
"Speed mode" or "just ship it" is not an override of any limit.

## The decisions log

Keep it as you go. Hand it back at the end.

```text
Decisions
1. <decision> -- <one-line reason>
2. <decision> -- <one-line reason> (deferred to coordinator)
3. <worker> on <model> -- <task>
4. <worker> step-up <from> to <to> -- <failure that caused it>

Stopped at limits
- <action> -- <which limit> -- <your recommendation>
```

The final report also gives the PR link, merge state, CI result, the worker
and step-up lines from the log, and status per environment.

## What this is not

- Not a way past a gate. Tests, CI and the merge gate still decide.
- Not [[np-flow-orchestrate]]. That mode keeps the user on every plan and risky
  merge across many tickets.
- Not [[np-core-dispatch]]. Dispatch supervises one handed-off task. Speed mode
  may use it to run workers.
