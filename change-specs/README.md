# Engine change specs

A `change-specs/<branch-slug>.md` file is the per-change record for a normal- or
high-tier engine change. It is read by CI (the `spec-guard` job), not only by a
human — that is why it lives in this repo rather than the content overlay.

## This is a different thing from `docs/superpowers/specs/`

`nervepack-content`'s `docs/superpowers/{plans,specs}/` holds personal design
docs the `brainstorming` and `writing-plans` superpowers skills produce during
planning conversations — private, not read by any automated gate, not tied to a
specific branch.

`change-specs/<branch-slug>.md` in **this** repo is a repo-governance artifact: it
declares what a branch is allowed to touch, and CI enforces it. Conceptually
it is closer to an ADR living in `doc/adr/` inside the repo it documents than
to a brainstorming spec. Both can exist for the same piece of work — a
brainstorming spec explains the reasoning at length in the overlay; this file
is the short, machine-readable contract CI checks the diff against.

## Naming

One file per branch: `change-specs/<branch-slug>.md`, where `<branch-slug>` is the
git branch name with `/` replaced by `-`. Example: branch
`feat/f1-spec-artifact` → `change-specs/feat-f1-spec-artifact.md`.

## Front matter

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Sequential, never reused. Zero-padded 4 digits. |
| `status` | yes | `proposed \| rejected \| accepted \| superseded by <NNNN>` |
| `date` | yes | ISO 8601, the date first opened |
| `tier` | yes | `standard \| normal \| high` — see the tier registry (#253/F7, not yet built) |
| `blast_radius` | yes | Path globs this change may touch. Enforced by drift-guard (#249, not yet built) |

## Status lifecycle and the immutability rule

`proposed` → `accepted` → `superseded by <NNNN>`, or `rejected` for a proposal
decided against before acceptance.

**An accepted spec is never edited into the new answer.** Write a new spec,
mark the old one `superseded by <NNNN>`, and cross-link. IDs are sequential and
never reused — this is the only mechanism that preserves *why* a rejected path
was rejected, and with one maintainer that is the only institutional memory
there is.

## `[NEEDS CLARIFICATION]`

Mark an underspecified point with this exact string rather than guessing.
`spec-guard` (#248, not yet built) will fail the PR while any marker remains.
Clear every one before implementation proceeds.

## When a spec is not required

Standard-tier changes (docs, wiki, skills, references, comments, test-only) and
spike-path work skip this file entirely. A process that demands one for every
change gets abandoned. Write one when three or more hold, per Google's
design-doc test: you are unsure of the right design; a senior perspective would
help; the design is contentious; cross-cutting concerns get overlooked; legacy
code needs documenting.

## Length

1–3 pages for an incremental change. 10–20 only for something the scale of a
new subsystem. Usefulness falls off past that — a spec that becomes
pseudo-code means the change was written twice.

## Deviations get recorded, not hidden

When implementation leaves the declared `blast_radius`, append to the spec's
`## Deviations` section rather than silently widening it or leaving it
inconsistent with the diff:

```markdown
## Deviations
- 2026-08-20 — also touched engine/setup/hooks/. Reason: the drift guard
  needed a registration point that did not exist. Blast radius widened.
```

You may deviate. The deviation is a written artifact.

## Worked example

`feat-f1-spec-artifact.md` in this directory is a real spec, using this
template, for the change that added this directory.
