# np-flow-skill-maintain

Agent prompt for the daily skill-split pass (`engine/setup/np_skill_maintain.py`,
dispatched via `cli.py cron skill-maintain`). The
cron appends the TARGET SKILL lines below and pipes the whole thing to
`claude -p --model claude-sonnet-4-6` via stdin.

## Prompt

You are performing a careful, mechanical refactor of ONE nervepack skill that has
grown over its body-size budget. Goal: shrink the SKILL.md body by moving DETAIL
into a `references/` sibling, WITHOUT changing what the skill means.

Rules:
- Keep in the SKILL.md body: the frontmatter (UNCHANGED), the skill's decision
  content — the rule, when-to-use/trigger, and any short essential code block.
- Move OUT to `references/<topic>.md` (create the dir): long checklists, multi-step
  recipes, large worked examples, verbose background prose. Use one or more
  topically-named reference files.
- In the body, REPLACE moved detail with a one-line pointer naming the reference
  file (e.g. "Full checklist: references/submission-checklist.md").
- NEVER edit the `name:` or `description:` frontmatter fields.
- NEVER drop a `[[cross-link]]` — every `[[...]]` present before must still appear
  somewhere in the body or a reference file afterward.
- Do not invent new content or change recommendations. This is a move, not a rewrite.
- Target: the body must end up under the stated hard budget.

Use Read to inspect the file, then Write/Edit to perform the move. Make no other
changes. Do not commit — the cron commits if validation passes.
