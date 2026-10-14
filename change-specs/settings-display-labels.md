---
id: 0079
status: accepted
date: 2026-10-14
tier: standard
blast_radius:
  - dashboard/index.html
  - engine/setup/tests/toggles/test_display_labels.py
  - change-specs/settings-display-labels.md
---

# 0079: Display labels for Settings toggles

## Context and problem statement

The dashboard Settings view shows raw toggle and param keys such as
`evaluator.dashboard_serve` and `skills.split_kb`. They are hard to read.
The keys themselves are stored in `toggles.local` and read by code, so they
cannot change.

## Considered options

1. Rename the keys. Bad, because it breaks existing `toggles.local` files.
2. Add a `label` column to `toggles.conf`. Bad, because it changes the manifest format every parser reads.
3. A label map in the dashboard. Good, because it is display-only and lives in one place.

## Decision

We will add a `TOGGLE_LABELS` map in `dashboard/index.html`. The Settings view
renders the label with the raw key smaller beside it. Unmapped keys render as before.

Chosen option: "label map in the dashboard", because it leaves stored keys untouched.

## Non-goals

Renaming keys. Labeling per-feature model overrides, which are already clear.

## Cross-cutting concerns

- Security: none. Labels pass through `esc()`.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because the Settings view reads as plain language.
- Bad, because a new param needs a label added by hand.
- Neutral, because the raw key stays visible for CLI use.

## Confirmation

`engine/setup/tests/toggles/test_display_labels.py` asserts every label key
exists in `toggles.conf`.

## Rollback

Revert the commit.

## Deviations
