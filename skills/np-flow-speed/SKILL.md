---
name: np-flow-speed
description: 'Use when the user wants a change delivered end to end with no clarifying questions or permission check-ins. Triggers: "speed mode", "/np-speed", "just ship it", "no questions", "don''t ask, just do it".'
---

# np-flow-speed

Speed mode delivers end to end without asking: brainstorm, plan, implement,
test, review, PR, review-bot resolution, merge on green, deploy, verify. It
ends with a decisions log. The hard limits
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
- Speed is not done at merge. It runs the finish line below until the change
  is deployed and verified live.

## Model tiering: cheapest model that fits

Speed mode delegates hands-on work to subagents. Each one runs on the cheapest
model that can do its job. The session default is never a worker's model.

| Work | Model |
|---|---|
| Search, file reads, lookups, mechanical edits, running tests, CI checks, git and PR steps | Haiku |
| Implementation, research, debugging, code review, multi-step edits | Sonnet |
| Coordination, hard calls, final verification | Coordinator (the session model) |

- Pass a model on every subagent spawn and every separate session. An unset model silently inherits the coordinator's model and costs the most. The coordinator rule is in [[np-flow-orchestrate]] § Worker models.
- Start each worker at its tier in the table. A worker fails when it reports it could not finish, or its output fails verification.
- A failed Haiku worker reruns once on Sonnet. A failed Sonnet worker escalates to the coordinator. If the coordinator cannot finish it either, it stops and surfaces it to the user.
- Record each step-up in the decisions log.
- The coordinator does no hands-on work a worker could do.
- Briefing and supervision follow [[np-core-dispatch]]. The tier split mirrors the model selection policy in `AGENTS.md`.

## The finish line

Opening the PR starts this phase. It ends only when the deploy has landed and
a live check passes. Do not hand back at "PR open" or "merged".

1. **Review bot.** On a repo with the bot ([[np-kb-pr-review-bot]]), wait for
   its review and the responder run. With no bot, or a run that posted
   nothing, use its route B: a read-only reviewer dispatched with [[np-core-dispatch]]. Either way a review happens.
2. **Resolve every thread.** Fix each real finding, then reply with the commit
   and resolve the thread. Resolve repeats and "undefined name" false
   positives with the evidence. Leave a human-decision question open and
   surface it. The bot's threads block merge under
   `required_review_thread_resolution`, and every push can add new ones, so
   re-query the threads after each push, not once. After 3 rounds that add no
   real finding, stop iterating and surface what remains.
3. **Merge on green.** Read `gh pr checks`. Pending, queued or missing is not
   green. If hosted CI cannot run, run the gate locally and say so.
4. **Deploy** by the repo's own recipe (its `CLAUDE.md` and deploy docs), in
   the repo's order, such as backend before site. A deploy runs when the repo
   or the user authorizes it. Otherwise it is a hard limit: stop and surface.
5. **Verify live.** Hit the deployed thing: a health route, a real response,
   the page in a browser, or the new infrastructure's own check. A green
   deploy command is not verification. Retry over a couple of minutes to ride
   out propagation, and log each result.
   A failed check means diagnose with the deploy output and the live response,
   never retry silently, then fix forward or roll back and say which. To roll
   back, use the repo's procedure or revert the merge commit, redeploy, and
   pass the same live check.
6. **Report** the PR, merge SHA, deploy result and the live check evidence.

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
