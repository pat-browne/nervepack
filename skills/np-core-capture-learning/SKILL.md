---
name: np-core-capture-learning
description: Single entry point for capturing something worth remembering. Classifies the input as durable (→ nervepack repo) or session-scoped (→ local Claude memory store) and routes it to the right destination. Use when the user says "capture this", "remember this", "save this learning", "/capture", or "/learn" — any phrasing that signals "this is worth keeping" without specifying where.
---

# np-core-capture-learning

The user-facing shortcut that hides the where-does-this-go decision behind
a single command. Internally it's a router: classify, then delegate to
either [[np-core-contribute]] or the local memory store.

## Trigger phrases

Any of these should invoke this skill:
- `/capture`, `/np-core-capture-learning`, `/learn`
- "capture this", "remember this", "save this learning"
- "this is worth keeping"

If the user explicitly says where it should go ("save to nervepack",
"add to memory") — skip this skill and use the targeted one directly
([[np-core-contribute]] or write to memory).

## The classification

Given a captured learning, ask: **would this still be useful to me on a
different project, a different machine, or six months from now?**

| Signal | Destination |
|---|---|
| Stable preference, rule, recurring pattern | **nervepack** (durable) |
| Environment quirk, tool gotcha, useful command | **nervepack** (durable) |
| Plugin choice, architectural taste | **nervepack** (durable) |
| Cross-cutting principle | **nervepack** (durable) |
| "Currently doing X" / "mid-debugging Y" | **memory** (session) |
| "Reminded me to do Z tomorrow" / "back from PTO Thursday" | **memory** (session) |
| Hostnames, paths, tokens, anything machine-specific | **memory** (session — and even then, avoid secrets) |
| Mid-conversation context the next session won't need | **memory** (session) |

When genuinely uncertain → **default to memory**. The daily
`memory-promote` cron will lift it to nervepack if it turns out to
be durable. Going the other way (demoting something out of nervepack) is
harder, so bias conservative.

## Steps

### 1. Classify
Read the user's intent. Apply the table above. State the verdict and the
reason in one sentence: "Saving to nervepack → it's a stable coding rule
that'll apply to every project" — or — "Saving to memory → it's about the
current PR you're debugging."

If the user disagrees, switch routes. They have final say.

### 2a. Durable → nervepack
Delegate to [[np-core-contribute]]. Follow its full protocol: sync first,
check `INDEX.md`, pick the right skill (extend over create), write the
edit, regenerate index, diff, commit, ask before push.

### 2b. Session-scoped → memory
Write to `~/.claude/projects/<your-project>/memory/<short-kebab-name>.md`
using the auto-memory format (see the system prompt's "How to save
memories" section — frontmatter with `name:`, `description:`,
`metadata: { type: ... }`). Add a line to `MEMORY.md`. Use the right type:

| Content shape | `type:` |
|---|---|
| Who the user is, what they're focused on | `user` |
| Behavioural correction or validation | `feedback` |
| In-flight project state, deadline, motivation | `project` |
| Pointer to an external system (Linear, Slack, doc URL) | `reference` |

### 3. Report
One sentence: where it went and why. Include the file path so the user
can verify.

## Why this skill exists

Without it, the user has to remember the distinction:
- `/np-core-contribute` = durable, cross-machine
- auto-memory write = session-scoped, this machine

That's friction at the moment of capture, which is exactly when friction
matters. `/np-core-capture-learning` removes the cognitive overhead — the user
just says "save this", and the routing happens transparently.

## What this skill does NOT do

- Does not push to nervepack without confirmation (delegates to
  [[np-core-contribute]] which has the push gate).
- Does not promote past memory entries — that's the daily
  `memory-promote` cron's job.
- Does not capture secrets, credentials, or PII. If the content includes
  any, refuse with one sentence and ask the user to redact.
