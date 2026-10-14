---
id: 0069
status: accepted
date: 2026-10-13
tier: normal
blast_radius:
  - engine/setup/np_skill_listing.py
  - engine/setup/tests/skills/test_skill_listing.py
  - engine/nervepack_engine/np_doctor.py
  - engine/onboard/capabilities.json
  - engine/setup/tests/onboard/test_np_doctor.py
  - skills/*/SKILL.md
  - docs/ARCHITECTURE.md
  - docs/FEATURES.md
  - engine/onboard/ONBOARD.md
  - INDEX.md
  - engine/setup/tests/run-all.sh
  - engine/setup/np_frontmatter.py
  - engine/setup/np_generate_index.py
  - engine/setup/tests/skills/test_np_frontmatter.py
  - change-specs/fix-skill-listing-budget.md
---

# 0069: Keep skill descriptions inside the host listing budget

## Context and problem statement

Claude Code sends the model one listing of every installed skill. It caps that listing at 1% of the context window, in characters, at 4 characters per token. That is 8000 characters at 200k context and 40000 at 1M.

Each entry costs `- <name>: <description>` plus a newline. Each description is cut at 1536 characters. When the listing runs over, the host keeps every name. It fills descriptions in priority order until the budget runs out. Every skill after that point shows as a bare name, and a bare skill never auto-triggers.

A measured install had about 230 skills and about 125000 characters of listing. About 40 nervepack skills showed as bare names. Short descriptions went bare too, so length alone does not pick the victims. Total size does.

## Considered options

1. Raise `skillListingBudgetFraction` on each machine. Bad, because it costs context every turn and leaves the repos unguarded.
2. Cap each description and each layer's listing share, and test both. Good, because it fixes the source and fails CI before a regression ships.

## Decision

Option 2.

`engine/setup/np_skill_listing.py` lints every `skills/*/SKILL.md`. It fails on missing frontmatter, a missing or empty `name` or `description`, and a plain YAML scalar that a strict parser rejects. It also fails on a description over the per-skill cap and a layer listing over its budget.

Defaults are 300 characters per description and 6000 characters per layer. Each layer passes its own budget, and env or flags override both. The engine suite lints the engine `skills/`. A content layer runs the same lint over its own tree.

`np_doctor` gains a SHOULD capability, `skill-listing`. It measures the installed listing against the host budget and warns when it runs over. Engine skill descriptions shrink under the cap, and each keeps its trigger phrases.

## Consequences

Plugin skills share the same host budget, and nervepack cannot edit them. The doctor warning names the total so the user can disable plugins. At 200k context the names alone nearly fill the budget, and no description length fixes that.

## Deviations

Added `engine/onboard/ONBOARD.md`, which lists the SHOULD capabilities by name. Added `INDEX.md`, which the index generator rebuilds from the new descriptions. Added `engine/setup/tests/run-all.sh`, which now exports `NP_ENGINE_ROOT` so a content-layer test can import the lint. Added `np_frontmatter.py` and `np_generate_index.py`, which now strip YAML quotes, because quoting is how a description holds a colon.
