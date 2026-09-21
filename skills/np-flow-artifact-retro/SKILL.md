---
name: np-flow-artifact-retro
description: The retro that runs right after publishing or revising an Artifact, dashboard or long work product, to capture what the session learned before the context is gone. Covers the fold-do-not-append rule that keeps a document from growing a new section per round, re-checking stale verdicts when new evidence lands, declaring a length budget and measuring it mechanically, and routing each learning to the right nervepack layer. Use after any Artifact publish, after a document revision round, or when the user says the doc is too long, asks to update rather than append, or corrects a conclusion the doc still carries. Symptoms it prevents: a two-page brief that reached six pages by accretion, a verdict left standing after the evidence moved, a gate rejection diagnosed from scratch for the sixth time, and a session's process lesson lost at compaction.
---

# np-flow-artifact-retro

A published Artifact is a work product AND a process sample. The publish is the
moment to harvest the second one, because the failures are still visible.

## When to run

- Immediately after an `Artifact` publish that took more than one attempt
- After a revision round on a doc that already existed
- When the user says "update the doc rather than append", "this is too long",
  or corrects a conclusion the doc still states
- Before a handoff or compaction on any document-shaped session

Skip it for a single clean publish of a throwaway page.

## The two failures worth catching every time

**Accretion.** A document revised in rounds grows a section per round, because
appending is easier than finding the paragraph that already owns the claim. The
result reads as a changelog and doubles in length without gaining a fact.

Before adding a section, name the section that already covers the topic and edit
that one. Delete the revision notices, the "what changed since" callouts and the
superseded figures as you go. Observed: a brief with a two-page budget reached
3,657 words and six figures across four rounds, with four overlapping cost
sections, two of which contradicted each other on the headline number.

**A stale verdict.** New evidence arrives in a later round and lands in a new
section, while the earlier verdict it refutes stays where it was. The document
then argues against itself, and the reader cannot tell which half is current.

After adding any figure or measurement, re-read every verdict, chip and summary
line upstream of it. Observed: a claim scored "Refuted" for one reason, while a
chart added two rounds later showed the claim held on a different driver.

## Length is a budget, not a feeling

Take the stated page count literally and convert it once: about 500 to 600 words
per page including table text, plus one or two figures.

Measure it mechanically rather than by eye, before publishing:

```bash
python3 -c "
import re,sys
try:
    s=open(sys.argv[1]).read()
except OSError as e:
    sys.exit(f'word count failed: {e}')
print(len(re.sub(r'<[^>]+>',' ',re.sub(r'<svg.*?</svg>','',s,flags=re.S)).split()))" <your-file.html>
```

When the count runs over, cut whole structures rather than shaving adjectives.
Overlapping sections merge, superseded figures go, and a table of ten rows that
supports one sentence becomes three rows.

## Then route what the session learned

Classify each item, then hand it to [[np-core-contribute]]. Do not write the
same lesson into two layers.

| What you learned | Where it goes |
|---|---|
| A rendering or publish-gate mechanic | `np-kb-artifact-authoring` |
| A fact about a vendor, product or bill | that domain's `np-kb-*` skill |
| A rule about how to run the work | this skill, or the matching `np-flow-*` |
| In-flight state only this task needs | session memory, not the repo |

Two classification traps. A gate rejection is an authoring mechanic, not a
process rule, so it belongs in `np-kb-artifact-authoring` with the others. A
vendor's "not supported" that later proved wrong is a domain correction AND a
reference lesson, and the reference file is where the reasoning survives.

## Five questions, answered in one line each

1. What did the user correct? That is the signal about a wrong prior, and the
   highest-value item in the retro.
2. What did I append that should have been an edit?
3. Which verdict or number is now stale somewhere else in the doc?
4. What cost more than one attempt, and what was the actual mechanic?
5. What did I assert without a measurement behind it?

Answer them plainly. A retro that grades the session instead of naming mechanics
produces nothing durable.

## Anti-patterns

- **Running the retro before publishing.** The publish is where the gate and the
  rendering fail, so a retro written first misses them.
- **Recording the narrative.** "We iterated on the layout" is not a lesson. The
  selector that lost to a specificity conflict is.
- **A new skill per session.** Extend an existing skill. Duplicate skills with
  overlapping descriptions are the failure this protocol exists to prevent.
- **Reporting a page count from impression.** Run the word count.

## Related

Rendering and publish-gate mechanics live in [[np-kb-artifact-authoring]], which
carries the forced-white wrapper trap, the full-bleed specificity failure, and
the concise-output gate's blank-line block scope. Form rules for the prose
itself are [[np-flow-concise-output]]. Delivering the diff of an edited markdown
file is [[np-flow-deliver-diff]]. Routing a durable learning is
[[np-core-contribute]], and the session-scoped half is
[[np-core-capture-learning]].
