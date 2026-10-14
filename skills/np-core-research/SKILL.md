---
name: np-core-research
description: Research a technical question from several version-pinned sources and give one recommendation with evidence, negative results and limits. Use on "research X", "what's the best practice for X", "is X still true", or when an answer would rest on stale memory.
---

# research: gather reputable sources, distill one answer

Answer from evidence, not memory. The output is a recommendation a reader can check claim by claim. Filing it in the wiki is a separate, approved step.

## 0. Check what nervepack already knows (every tier, never skip)

Run the defer-first lookup in `AGENTS.md` before searching the web. Check `INDEX.md`, then `wiki/topics/` and `wiki/concepts/` in `$NP_CONTENT_DIR`. A pinned source that covers the question wins. Re-research only to check its currency or fill a named gap.

## 1. Scope and pick a tier

Write the question as one sentence plus the decision it feeds. Split it into sub-questions that can be answered independently.

| Tier | When | How |
|---|---|---|
| Quick | One fact, one API, one version check | 1 to 3 official sources, inline |
| Deep | A design choice, a standard, competing options | One parallel agent per sub-question, then verify and synthesize |

Default to quick. Step up when sources disagree or the answer drives architecture.

## 2. Gather (deep tier: fan out)

Dispatch one research agent per sub-question in a single message so they run concurrently. Give each one the sub-question, the source rules below, and the output fields in step 5. Barrier: wait for all of them before verifying.

**Source rules.** Use official technical reference: specs, RFCs, standards bodies, vendor docs, official tutorials, and peer-reviewed papers. Record the URL, the exact version or date, and the section consulted. Skip vendor blogs, listicles, aggregators, and anything written to sell.

**Exception.** GitHub issues and maintainer comments count as evidence of a failure mode or a regression. Cite them as such. Never ingest them as sources.

## 3. Verify adversarially

For each load-bearing claim, try to refute it rather than confirm it. On the deep tier, give independent skeptics the claim and ask for contradicting evidence. One cited contradiction kills or qualifies a claim.

| Failure mode | Check |
|---|---|
| Stale | Open the live source and confirm the version and section still exist |
| Misattributed | Confirm the cited control, clause, or API actually says this |
| Scope-stripped | Restore the conditions a finding was measured under |
| Cross-option | Look for a constraint that applies to every option once compared |

## 4. Synthesize

Lead with the recommendation and the preconditions it depends on. Name the cheapest check that would prove each precondition. Keep the reasoning short and tie every claim to a source.

## 5. Output contract

1. **Recommendation**, with preconditions.
2. **Evidence**: each claim with its source, version, and section.
3. **Currency corrections**: what changed from common belief or model memory.
4. **Negative results**: what does not exist, does not apply, or was refuted.
5. **Limits**: paywalled, image-only, unreachable, or unverified sources.

Pass the draft through [[np-flow-concise-output]] before sending.

## 6. File it (only on approval)

Offer to ingest when the answer is source-worthy: repeat-volume, version-pinned, and worth cross-linking. Use the ingest protocol in `AGENTS.md`, including the cap and rotate prompt, via [[np-core-contribute]]. A deep-tier result becomes a topic synthesis page plus `kind: reference` sources, and a `log.md` entry.

For a one-off or bleeding-edge question, answer and stop. Use context7 for a live API lookup rather than ingesting it.

## Not this skill

- Recalling past sessions: [[np-core-recall]].
- Saving a learning you already have: [[np-core-capture-learning]].
- Building the thing once researched: [[np-flow-develop]].
