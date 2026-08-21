---
name: np-core-layout
description: Learn and record how a content layer is organized, so contributions land in the right place without the engine hardcoding a directory tree. Use when onboarding a new content or team layer, when np-doctor reports layer-layout as inferred, when a contribution reports no declared route for its kind, or when the user asks where something should go in a knowledge repo.
---

# np-core-layout

A layer declares where its content lives in `.nervepack/layout.json`. The engine
owns the kinds. The layer owns the paths. Links and `INDEX.md` make content
findable, so directory structure is human convenience, not a contract.

## Kinds

| Kind | Meaning |
|---|---|
| `skill` | Behavioral how-to the agent loads |
| `knowledge` | A synthesis page the user wrote |
| `reference` | Curated external source material |
| `roadmap` | Deferred work |
| `prompt` | A recurring agent prompt |

A layer may split one kind into **variants**, each with a `when` rule that says how
to choose. Topics and concepts are one layer's split of `knowledge`, not an engine
concept.

## When to run the interview

- Onboarding a new personal or team layer.
- `cli.py doctor` reports `layer-layout` as inferred, or with open questions.
- A contribution reports no route for its kind.

## The interview

1. Read the current state:
   ```bash
   NP="${NP_DIR:-$HOME/Code/nervepack}/engine/nervepack_engine/cli.py"
   python3 "$NP" layout show --layer personal
   python3 "$NP" layout questions --layer personal
   ```
2. Read every doc in the layout's `derived_from` list **before you ask anything**.
   Prose often answers a question, and an answered question is never asked.
3. Reconcile the prose against the inferred routes. Where they disagree, the disk
   wins: inference reports what pages actually do. Record what the prose settles.
4. Ask the user **one question**. Never batch them.
5. Apply the answer to the layout, then **re-run** `layout questions` against the
   updated layout. One answer often settles several questions.
6. Ask the next surviving question. Repeat until the list is empty.
7. Record and show the result:
   ```bash
   printf '%s' "$LAYOUT_JSON" | python3 "$NP" layout record --layer personal
   git -C "$LAYER" diff -- .nervepack/layout.json
   ```
8. Ask before committing. The manifest is a repo file, and a team layer needs a PR.

Step 5 is the rule that matters. Asking a question a prior answer already resolved
is the failure this protocol exists to prevent.

## Hard rules

- Never invent a directory. If a kind has no home, ask.
- Never write a route that leaves the layer root. `route()` refuses it anyway,
  because a team manifest is remote-writable input.
- A directory that is not a contribution target goes in `unmapped`, so the
  interview stops asking about it.
- Do not migrate the layer's files. The manifest describes the tree that exists.
- Do not edit the engine to add a path. That is the bug this skill removes.

Worked example, the manifest field reference, the answer-to-route mapping, and the
read-only-layer cache: references/interview.md

See [[np-core-contribute]] for what happens after a route resolves, and
[[np-core-onboard]] for where this runs during setup.
