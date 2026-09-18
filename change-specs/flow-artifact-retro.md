---
id: 0037
status: accepted
date: 2026-09-18
tier: normal
blast_radius:
  - skills/np-flow-artifact-retro/**
  - .claude-plugin/plugin.json
  - INDEX.md
  - change-specs/flow-artifact-retro.md
---

# 0037 — A retro flow for Artifact and long-document sessions

## Problem

A document revised across several rounds grows a section per round. Appending is
cheaper than finding the paragraph that already owns the claim, so the doc reads
as a changelog and outgrows its stated length.

Two live examples from one session. A brief with a two-page budget reached 3,657
words, six figures and four overlapping cost sections, two of which disagreed on
the headline number. A verdict scored "Refuted" stayed standing after a chart
added two rounds later showed the claim held on a different driver.

Nothing in the skill set covered either failure. `np-kb-artifact-authoring`
carries rendering and gate mechanics, and `np-flow-concise-output` carries
sentence form. Neither addresses document-level accretion or stale verdicts.

## Change

Add `skills/np-flow-artifact-retro`, a flow that runs at publish time. It
carries the fold-do-not-append rule, the stale-verdict re-read, a mechanical
word-count check against the stated page budget, and a routing table that sends
each learning to one layer rather than two.

Register it in `.claude-plugin/plugin.json` and regenerate `INDEX.md`.

## Alternatives rejected

**Extend `np-kb-artifact-authoring`.** That skill is already 7.9 KB against an
8 KB hard cap, and its subject is rendering rather than revision discipline.

**Extend `np-flow-concise-output`.** Its scope is sentence and paragraph form.
Document structure across revisions is a different grain, and widening that
skill would dilute a gate that already fires on every draft.

**Session memory only.** The lesson repeats across documents and projects, so it
belongs in the engine rather than in one project's memory.

## Verification

`np_risk_tiers` resolves the change set to normal tier, which this spec covers.
The skill body is 5.5 KB, inside the 6 KB soft cap. Relink and index regenerate
cleanly, and the plugin manifest stays valid JSON.
