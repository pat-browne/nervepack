---
name: np-core-toggle
description: Turn Nervepack features on/off and adjust their settings. Use when the user says "toggle off X", "disable memory/playbooks/allowlist/the directive", "turn X back on", "what nervepack features are on", or wants to change the sync interval. Wraps setup/nervepack-toggle.sh.
---

# np-core-toggle

Nervepack features each have an on/off toggle declared in `engine/setup/toggles.conf`.
Use the CLI:

- **List state:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh status`
- **Flip:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh <feature> on|off`
- **Set a param:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh param sync.interval 3600`
- **Interactive picker:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh` (no args)
- **Audit:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh audit`

Families: `memory` (capture/recall/maintain/promote), `playbooks` (guard/recall),
`directive`, `sync` (with `sync.interval`, default 86400s/1 day), `allowlist`
(Claude permission entries — managed, install/remove). Sub-toggles like
`memory.recall` inherit their family unless explicitly set.

**Scope:** shared features (memory/playbooks/directive/sync) commit their state to
the repo and propagate on the next sync; local features (allowlist) and any
sub-override write to `~/.config/nervepack/toggles.local`.

**Sync:** primary sync runs on session exit (`SessionEnd`); the throttled
`SessionStart` sync (default 1 day) is a backup. Change with
`nervepack-toggle param sync.interval <seconds>`.

**When adding a NEW Nervepack feature, add a `toggles.conf` row and wire its
enforcement** (`np_enabled` guard for runtime/cron, install/remove for managed) —
see `CLAUDE.md` § "Feature toggles".
