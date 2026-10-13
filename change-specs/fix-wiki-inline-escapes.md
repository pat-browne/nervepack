---
id: 0063
status: accepted
date: 2026-10-13
tier: normal
blast_radius:
  - dashboard/build.py
  - engine/setup/tests/evaluator/test_dashboard_render.py
  - change-specs/fix-wiki-inline-escapes.md
---

# 0063: Render Word-export bookmarks and backslash escapes in wiki pages

## Context and problem statement

Pages converted from Word carry empty `<a id="...">` bookmarks and Markdown
backslash escapes such as `\_` and `\(`. The renderer escaped both, so data-base
data-model pages showed raw tags and backslashes in the body and the nav excerpt.

## Considered options

1. Keep bookmarks as link targets and undo backslash escapes in the renderer. Good, because the table-of-contents links keep working.
2. Strip the markup from the content repo. Bad, because the next export brings it back.

## Decision

We will park bookmark anchors and escapes behind sentinels before HTML-escaping,
then restore them as a sanitized `<a id>` and the literal character. Excerpts drop
bookmarks and escapes. `__bold__` renders as bold.

Chosen option: "fix in the renderer", because the content is valid Markdown.

## Non-goals

General raw-HTML support. Every other tag stays escaped.

## Cross-cutting concerns

- Security: only `<a id|name="[A-Za-z0-9_.:-]+"></a>` passes, rebuilt from the captured id. Other HTML stays escaped.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because data-model pages read cleanly and their TOC links resolve.
- Neutral, because two extra regex passes run per inline run.

## Confirmation

`TestWordExportMarkup` in test_dashboard_render.py. A real-content build has 0 pages with escaped anchors.

## Rollback

Revert this PR.

## Deviations
