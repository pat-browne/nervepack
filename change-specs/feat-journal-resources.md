---
id: 0101
status: proposed
date: 2026-10-26
tier: high
blast_radius:
  - engine/nervepack_engine/np_journal.py
  - engine/nervepack_engine/np_resources.py
  - engine/nervepack_engine/hooks/backcapture_sweep.py
  - engine/setup/np_agentic_cron.py
  - engine/setup/toggles.conf
  - engine/setup/toggle-schema.json
  - engine/setup/tests/journal/**
  - agents/np-flow-episodic-maintain.md
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - AGENTS.md
  - change-specs/feat-journal-resources.md
---

# 0101: Richer session journal, resources catalog, crawl before cleanup

## Context and problem statement

The PreCompact journal keeps five fields. It loses decisions, wins, open
questions, the next step, touched files, and the identifiers a session used.

The backcapture sweep deletes a journal after capture. A 30-day TTL deletes the
rest. Neither path analyzes the journal, so its struggles and wins never reach
the lessons layer.

## Considered options

1. **Inbox, drained by episodic-maintain** (chosen). The crawl stages records in
   local inboxes and the cron drains them into the overlay. This matches the
   capture invariant that hot paths never touch the committed overlay.

2. **Direct append to the overlay in the sweep.** Rejected. It puts git-tracked
   writes in a background SessionStart path and races the cron commit.

3. **Let the maintain agent merge resources.** Rejected. Dedup by identifier is
   exact work, so Python does it and the agent only commits.

## Decision

Add `wins`, `decisions` (with reason), `open_questions`, `next_step`, and
`files_touched` to the journal block.

Each new field is capped at 400 characters and omitted when empty. Restored
context keeps the seed block and the newest three blocks, capped at 12000
characters.

New `np_resources.py` extracts identifiers by regex, then redacts. Haiku, the
existing pinned journal call, only labels the purpose of ids the regex found.
It cannot add an id.

Before the sweep or the TTL deletes a journal, `np_journal.crawl` sends struggles
and wins to the episodic inbox and resources to a resources inbox. A failed
crawl keeps the journal. A receipt prevents a second crawl.

`episodic_maintain()` drains the resources inbox in Python into
`memory/resources/<YYYY-MM>.jsonl` and rewrites `memory/resources/INDEX.md`.
The maintain agent commits that path.

Param `journal.crawl`, default on, gates the crawl and the drain.

Model verdict: Haiku, single-shot labeling. No new model call is added.

## Non-goals

Backfilling resources from old transcripts is out. Capturing secret values is
out. Names only.

## Cross-cutting concerns

- Security: values are redacted before extraction and before the model sees the
  candidate list. A candidate that still looks like a credential is dropped. The
  scrub runs again at stage, at drain, and over every journal block.

- Privacy: identifiers can name internal hosts. They stay local until the
  overlay commit, which goes to the private repo.

- Observability: the crawl logs failures to `session-journal.log`.

## Consequences

- Good, because lessons now see journal struggles that capture missed.

- Good, because the catalog answers where a host appeared across sessions.

- Bad, because regex extraction yields some false positives. The model label
  and the 40-per-session cap bound the noise.

- Neutral, because the restored journal is shorter on long sessions.

## Confirmation

`engine/setup/tests/journal/test_journal_resources.py` proves extraction,
redaction of every secret shape, dedup, month files, INDEX grouping, crawl
ordering, TTL crawl, and the param gate.

## Rollback

1. Run `cli.py toggle journal.crawl off`. The crawl and the drain stop at once.

2. Revert the merge commit. Old journal blocks still parse.

3. Delete `memory/resources/` in the overlay if the catalog is unwanted. Nothing
   reads it.
