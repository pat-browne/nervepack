---
name: np-core-recall
description: Pull episodic working-memory themes ("what we did / decided / where we left off") from nervepack's episodic/ layer on demand. Use when the user says "/recall", "what did we do on X", "remind me where we left off on Y", or wants prior-session context that wasn't auto-injected. Read-only — episodic is the lowest-authority layer; durable skills/sources/wiki override it.
---

# recall

The on-demand counterpart to the automatic `UserPromptSubmit` injection
(`engine/setup/episodic-recall.sh`). Auto-injection only fires on a session's first
couple of prompts and only on keyword hits; `/recall` lets you pull any theme,
any time.

## Trigger phrases
- `/recall`, `/recall <topic-or-keywords>`
- "what did we do on X", "where did we leave off on Y"
- "pull up our prior context about Z"

## Steps

### 1. Locate candidate themes

Episodic lives in the **content overlay** under `memory/episodic/`, not the
engine repo. Resolve the roots (merge-aware, team > personal):

```bash
source ~/Code/nervepack/engine/setup/np-layer-lib.sh
np_layer_roots episodic            # one dir per overlay root
```

For each root: `ls <root>/*.md` (available themes) and `sed -n '1,80p'
<root>/INDEX.md` (topic | keywords index). Match the user's query against topic
slugs and the `keywords` column. If they gave no query, list the most recently
updated themes and ask which.

### 2. Read the matching theme(s)
Read `<root>/<topic>.md` for the best match(es). Prefer the most recent
entries; mention the `## Rolled-up summary` block if older context is relevant.

### 3. Present
Summarize what was done / decided / where it was left off, citing the file
path. **Flag the authority level**: episodic context is working narrative and
may be stale — if it conflicts with a `skills/`, `sources/`, or `wiki/` page,
the durable layer wins. Say so when relevant.

## What this skill does NOT do
- Does not write to the episodic layer (capture + the episodic-maintain agent own writes).
- Does not promote anything to `skills/` — if a recalled entry is actually a
  durable rule, route it through [[np-core-contribute]].
- Does not surface secrets; if a theme somehow contains one, redact in your
  reply and note it for cleanup.
