---
name: np-core-handoff
description: Compact the current conversation into a handoff document a fresh agent can pick up from — written to the OS temp dir (never the repo), with a suggested-skills section and any secrets/PII redacted. Use when the user says "/handoff", "hand this off", "write a handoff", or "summarize this for the next session"; when context is about to run out or before a compact; or when switching agents/machines mid-task. Pairs with [[np-core-recall]] (its inverse — recall pulls prior context back; handoff pushes it forward).
argument-hint: "What will the next session be used for?"
---

# handoff — compact a session for the next agent

Write a handoff document so a **fresh agent with none of this conversation's context**
can continue the work. The reader is an agent, not a person — optimise for "what does
the next session need to know to act," not narrative.

## Where it goes

Save to the **OS temp directory** (`${TMPDIR:-/tmp}/handoff-<short-slug>.md`), **never**
the current workspace or `~/Code/nervepack`. A handoff is ephemeral working state, not a
durable artifact — committing it pollutes the repo and the publish surface.

## What to include

- **The objective** — what we're trying to accomplish, and the current position toward it.
- **State** — what's done, what's in flight, what's blocked and on what (decision, creds,
  a reachable box, a review).
- **Next concrete step** — the single most useful thing the next agent should do first.
- **Suggested skills** — name the specific nervepack skills the next session should invoke
  (e.g. `[[np-core-recall]]` to pull prior episodic themes, `[[np-core-sync]]` if the repo
  may have moved, plus any domain `np-kb-*`/`np-env-*` skills the task touches). The
  SessionStart directive re-lists skills passively; naming the relevant ones here turns
  that into a directed pickup.

## Always surface the file, not just its path

Once the doc is written, send it to the user (e.g. a file-delivery tool if the host
provides one) so it opens for review immediately — don't just state the path in text and
wait to be asked. A handoff is written *for* the user to review before dispatch as much as
for the next agent to read; a path mentioned in passing is easy to miss or skip past, and
review is the entire reason this is a separate document instead of an inline message.

## Rules

- **Reference, don't duplicate.** Anything already captured in a plan, spec, ADR, issue,
  commit, diff, or `docs/` file — link it by path or URL. Don't restate it.
- **Redact secrets/PII.** No API keys, passwords, tokens, or secret-bearing paths in the
  doc — pull them fresh next session via [[np-env-secrets-refresh]] instead. (LAN IPs and
  private-box addresses are noise too — reference by name, not literal, per the repo's
  publish-cleanliness stance.)
- **Honor the argument.** If the user passed `$ARGUMENTS` (or answered the argument-hint),
  treat it as the next session's focus and tailor the doc to it — lead with what serves
  that goal, trim the rest.
- **Run a retrospective before writing the doc.** Ask: what did this session assume that
  turned out wrong, and what corrected it? Fold silently-corrected assumptions (a wrong
  guessed path, a stale checkout, a bad sample) into the handoff's state section, and
  capture anything durable via [[np-core-contribute]] rather than leaving it only in the
  transcript the next agent won't see.

## When NOT to use this (vs. the rest of the continuity family)

- **[[np-core-recall]]** — the inverse direction: *read back* prior-session themes. Use it
  at the START of a session; use handoff at the END.
- **Episodic layer** (auto-captured) — background "what we did" narrative the SessionEnd /
  back-capture sweep writes on its own. Handoff is the **explicit, on-demand, task-focused**
  document for a *specific* continuation — richer and aimed, where episodic is ambient.
- **[[np-core-capture-learning]] / [[np-core-contribute]]** — for anything *durable* (a rule,
  preference, decision worth keeping across many sessions). A handoff is for THIS task's
  continuation only; promote durable facts to a skill instead of burying them in a temp doc.
- **[[np-core-dispatch]]** — the *send* half of the pair: once the handoff is written,
  dispatch it to a fresh agent (and the fallback for when `SendMessage` to a warm agent
  isn't available). Write with handoff, send with dispatch.

## Quick reference

| Step | Do |
|---|---|
| 1 | Read `$ARGUMENTS`; if present, scope the doc to that focus |
| 2 | Draft: objective → state (done / in-flight / blocked) → next concrete step |
| 3 | Add a **Suggested skills** section naming specific nervepack skills to invoke |
| 4 | Reference existing artifacts by path/URL; redact secrets/PII |
| 5 | Write to `${TMPDIR:-/tmp}/handoff-<slug>.md` |
| 6 | Send the file to the user so it opens for review — don't just report the path |
