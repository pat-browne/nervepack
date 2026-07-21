# Open specs/plans in focus on write

**Date:** 2026-07-21
**Status:** approved (single-session design, scope small enough to skip full brainstorming ceremony)

## Problem

`superpowers:brainstorming` writes specs to `docs/superpowers/specs/*.md`;
`superpowers:writing-plans` writes plans to `docs/superpowers/plans/*.md`. Both
are meant to be read and approved by the human before implementation proceeds,
but today the only signal is a line of chat text ("Spec written to ..."). It's
easy to skim past and rubber-stamp without actually opening the file. The ask:
whenever such a file is created, open it in focus so the human's attention is
actually drawn to it.

## Design

A new **engine** feature (this is a session-lifecycle mechanism, not
Pat-specific content) mirroring the existing `open-dashboard` hook:

- **Hook:** `PostToolUse`, matcher `Write`, dispatched as `cli.py hook
  open-artifact` → `engine/nervepack_engine/hooks/open_artifact.py`.
- **Match rule:** the written `file_path` matches
  `.../docs/superpowers/(specs|plans)/*.md` (regex on the path, cross-platform
  separators). Only `Write` (creation), not `Edit` — the ask is "when a plan or
  spec is *made*", not every subsequent revision.
- **Open mechanism:** reuse `np_dashboard.resolve_opener()` (already resolves
  `xdg-open`/`open`, `NP_DASH_OPENER` override, `""` if none) — `open <path>` /
  `xdg-open <path>` both work fine for local files, not just dashboard URLs.
  No new opener-resolution logic needed.
- **Toggle:** new family `focus` (`shared|runtime|on`, no params yet — YAGNI on
  configurable globs/opener until a real need shows up).
- **Fail-open:** bad JSON, missing fields, no resolvable opener, wrong tool,
  non-matching path, or file missing on disk → silently return `""`. Never
  blocks the Write tool call (PostToolUse hooks don't block anyway, but the
  no-throw contract still matters for the transcript/log).
- **Not in scope:** doctor capability (the existing generic `hook-scripts`
  wiring check already covers "is this hook registered"; a dedicated
  capability is unwarranted ceremony for one small hook), Edit-triggered
  reopens, per-repo config of the specs/plans path (it's a fixed
  superpowers-wide convention, not something projects vary).

## Alternatives considered

1. **Bake it into the brainstorming/writing-plans skill bodies** (have the
   skill instructions say "run `open <path>` after writing"). Rejected: skills
   are Markdown instructions the model may or may not execute faithfully every
   time; a hook is deterministic and can't be skipped by an inattentive
   session.
2. **Content-overlay skill instead of engine hook.** Rejected: the
   specs/plans convention is used across every one of Pat's repos (confirmed
   in data-team-mcp's own CLAUDE.md and nervepack-content's own plans dir) —
   this is generic machinery, not personal knowledge content, so it belongs in
   the engine per the np-core/np-kb split.

## Testing

Hermetic Python unit test
(`engine/setup/tests/nervepack_engine/test_open_artifact.py`), same shape as
`test_open_dashboard.py`: injectable `opener_fn`, toggle on/off, tool_name
filter, path-match filter (positive + negative cases for specs/, plans/, and a
non-matching `docs/` file), missing-file-on-disk skip, no-opener-available
fail-open.
