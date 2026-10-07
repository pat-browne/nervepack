---
id: 0061
status: accepted
date: 2026-10-07
tier: normal
blast_radius:
  - dashboard/index.html
  - engine/setup/toggle-schema.json
  - engine/setup/tests/evaluator/test_dashboard_settings_models.py
  - engine/setup/tests/e2e/test_toggle_panel_flow.py
  - change-specs/dashboard-models-in-settings.md
---

# 0061: Models panel moves into the settings modal

## Context and problem statement

The Models panel sat on the main dashboard page. The toggle list in the settings
modal showed the same models.* params as free-text inputs, so one setting had two
editors. Help tooltips clipped at the modal's left edge, and several toggle
families and params had no help text.

## Considered options

1. Move the Models panel into the settings modal and hide models.* params from the
   toggle list. Good, because each setting gets one editor. Bad, because the
   models are one click further away.
2. Keep the panel on the main page and drop the models.* inputs. Good, because
   nothing moves. Bad, because model choice stays split from the other settings.

## Decision

We will render the Models section inside the settings modal, above Feature toggles.
The modal title reads Settings. The missing-model banner stays on the main page.
Its #model-row links, and a #model-row hash on load, open the modal and scroll to
the row.

The toggle list shows the models family switch with a pointer to the Models
section. One fixed-position tooltip bubble replaces the CSS ::after bubble and
clamps to the viewport. Every family and param in toggles.conf gets a schema
description.

Chosen option: "Option 1", because it leaves one editor per setting.

## Non-goals

No change to the /api/models or /api/toggles contracts, or to build.py.

## Cross-cutting concerns

- Security: none. Same endpoints, same escaping.
- Privacy: none.
- Observability: none.

## Consequences

- Good, because the main page loses a panel most sessions never touch.
- Bad, because the newly typed schema entries make those params editable in the UI.
- Neutral, because models data still loads on page load for the banner.

## Confirmation

engine/setup/tests/evaluator/test_dashboard_settings_models.py pins the modal
markup, the banner link wiring and the description coverage. The e2e toggle flow
covers the tooltip clamp and the hash open.

## Rollback

Revert the PR.

## Deviations
