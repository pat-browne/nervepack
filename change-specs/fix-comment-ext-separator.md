---
id: 0025
status: proposed
date: 2026-09-02
tier: high
blast_radius:
  - engine/nervepack_engine/hooks/form_gate.py
  - engine/setup/tests/nervepack_engine/test_form_gate.py
  - change-specs/fix-comment-ext-separator.md
---

# 0025: comment_ext and prose_ext accept a colon-joined list

## Context and problem statement

Spec 0024 added the `comment_ext` param. A maintainer sets it to a list of
extensions. The value looked like it should read `.py,.ts,.sh`, comma-joined,
the way the Python default constant is written.

That form does not work. `np_toggle` tokenizes the params field on `[ ,]+`, so a
comma inside a value splits the field. A conf value of `comment_ext=.py,.ts,.sh`
resolves to `.py` alone. `exempt_globs` already avoids this by joining its list
on a colon.

`_comment_ext` and `_prose_ext` both split their value on a comma only. So even
a colon-joined conf value would arrive as one un-split extension. Neither param
can hold a working multi-extension list today.

## Decision

Both functions now split on comma OR colon. A conf value uses colons, which
survive the resolver. The Python default constants keep their commas and still
work. A maintainer writes `comment_ext=.py:.ts:.sh`.

## Considered options

Single extension only was rejected. A maintainer wants a stack.

Changing the `np_toggle` params parser was rejected. That parser is shared by
every feature, so widening the fix there risks far more than this needs.

Accepting both separators in the two helpers was chosen. The change is two lines
and touches only the feature that needs it.

## Non-goals

The `np_toggle` params parser is unchanged. `exempt_globs` is unchanged.

## Confirmation

A new test asserts a colon-joined `comment_ext` resolves to every extension. The
full suite passes, aside from the known unrelated `test_dashboard_lifecycle.py`
failure already on `main`.

## Rollback

Revert the merge commit. No hook registration change is needed.

## Deviations

(none yet)
