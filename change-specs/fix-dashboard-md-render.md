---
id: 0040
status: accepted
date: 2026-09-24
tier: normal
blast_radius:
  - dashboard/build.py
  - engine/setup/tests/evaluator/test_dashboard_render.py
  - change-specs/fix-dashboard-md-render.md
---

# 0040: dashboard wiki pages render broken bold and rules

## Context and problem statement

The dashboard renders wiki Markdown to HTML with `md_to_html` in
`dashboard/build.py`. Most rendered wiki pages showed stray asterisks and
broken `<em>` fragments. Horizontal rules showed as literal `---` text.

Three defects caused this:

1. The list-marker strip used an unanchored `re.sub`. It removed every
   `- ` or `* ` in the item, not only the leading marker. A closing `**`
   followed by a space lost its last asterisk, so the bold pair broke.
2. The bold regex `\*\*([^*]+)\*\*` rejected any `*` inside the span. Text
   such as `**COUNT(*) vs COUNT(col):**` never matched as bold.
3. The renderer had no thematic-break branch. A `---` line became a
   paragraph.

## Considered options

1. Fix the three regexes in place. Good, because the change is small and
   keeps the stdlib-only renderer.
2. Replace the renderer with a Markdown library. Bad, because the engine
   takes no third-party dependencies.

## Decision

We will anchor both list-marker strips with `^`, make the bold match
non-greedy, and render `---`, `***`, and `___` lines as `<hr>`.

Chosen option: "Fix the three regexes in place", because it fixes the
output with no new dependency.

## Non-goals

Full CommonMark emphasis rules. The italic pass still pairs single
asterisks. No current page hits that case.

## Cross-cutting concerns

- Security: output stays escaped. `html.escape` still runs first.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because every rendered wiki page now shows correct bold and rules.
- Neutral, because pages rebuild on the next dashboard build.

## Confirmation

Four new cases in `engine/setup/tests/evaluator/test_dashboard_render.py`
fail on the old renderer and pass on the new one. A sweep of all rendered
wiki pages finds zero `<p>---</p>`, `*<em>`, or `</em>**` fragments.

## Deviations
