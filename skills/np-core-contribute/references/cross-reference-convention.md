# How to reference another skill from inside skill content

Use the repo's own cross-reference convention. Never a relative markdown
link to another skill's file.

## Why a relative link fails

A relative link like `../pr/SKILL.md` assumes a specific sibling directory
layout: this skill and that skill both live under the same parent, at the
same depth, forever. That assumption breaks under any of these, and none of
them are rare:

- The skill gets symlinked into a host's skill directory from a different
  physical location, which changes the resolution root.
- The skill gets ported into a different repo that does not have the
  linked-to skill at all, or has it at a different depth.
- Either skill moves during a later reorganization.

A bare name reference has none of these failure modes, because it names a
concept the reader or the Skill tool resolves, not a path on a filesystem.

## The convention differs by repo, and that is fine

Nervepack's own convention is a double-bracket wikilink: `[[skill-name]]`,
resolved by name (see this repo's own `AGENTS.md`, "Cross-link related
skills with `[[skill-name]]`. Dangling links are fine.").

A repo without wikilink resolution, such as a `.claude/skills/` tree with no
special markdown handling, uses a plain backtick name instead: `` `pr` skill
``, `` `concise-output` skill ``. Both conventions name-reference; neither
uses a path.

**When writing content for a specific repo, match that repo's own
convention.** Do not import nervepack's `[[wikilink]]` syntax into a repo
that has never used it, and do not introduce a relative path into nervepack
because a different repo you were just working in used plain names.

## The incident

A session wrote a PR-description shape into a `data-base` skill (`concise-
output`), cross-referencing a sibling skill (`pr`) with a relative markdown
link: `` [`pr`](../pr/SKILL.md) ``. That repo's own dominant convention,
visible in a dozen other skills, is a plain backtick name with no path. The
same session had, minutes earlier, ported a version of the same content into
this repo's overlay, where the wikilink convention applies and no `pr`
skill exists at all. The relative link would have been doubly wrong there:
wrong convention, and pointing at a file that is not present.

Corrected in both places once flagged: every cross-skill reference rewritten
to the convention already dominant in the file being edited, checked by
grep before writing, not assumed.

## Check before writing

Before adding any cross-skill reference, grep the file (or a few sibling
skill files) for the pattern already in use:

```bash
grep -n '\[\[.*\]\]' <file>          # wikilink convention
grep -n '`[a-z-]*` skill' <file>     # plain-name convention
grep -n '\](\.\./.*SKILL\.md)' <file>  # relative link, a candidate for fixing
```

Match whichever convention the grep turns up. If the file has neither yet,
default to a plain backtick name. It degrades gracefully in every host,
since a name a reader cannot click is still a name they can read.
