---
name: np-core-toggle
description: Turn Nervepack features on/off and adjust their settings. Use when the user says "toggle off X", "disable memory/lessons/the evaluator/the directive", "turn X back on", "what nervepack features are on", or wants to change a param like the sync interval. Wraps engine/setup/nervepack-toggle.sh.
---

# np-core-toggle

Nervepack features each have an on/off toggle declared in `engine/setup/toggles.conf`.
Use the CLI:

- **List state:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh status`
- **Flip:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh <feature> on|off`
- **Set a param:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh param sync.interval 3600`
- **Interactive picker:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh` (no args)
- **Audit:** `~/Code/nervepack/engine/setup/nervepack-toggle.sh audit`

Families (full param list in `toggles.conf`): `memory` (capture/recall/promote +
back-capture params), `lessons` (auto-distilled lessons; `.enforce`), `directive`,
`sync` (`interval`, default 86400s/1 day), `allowlist` (managed Claude permission
entries), `evaluator` (metrics + dashboard/suggestions/implement params), `skills`
(budget + graduation params), `team` (`merge` mode), `mcp` (`writes`/`contribute`),
`maintain` (`.refine`/`.compact` weekly crons), `pii_filter` (default off).
Sub-toggles like `memory.recall` inherit their family unless explicitly set.

**Scope:** shared features commit their state to the repo and propagate on the
next sync; `allowlist` (local) and any sub-override write to
`~/.config/nervepack/toggles.local`.

**Sync:** primary sync runs on session exit (`SessionEnd`); the throttled
`SessionStart` sync (default 1 day) is a backup. Change with
`nervepack-toggle param sync.interval <seconds>`.

**When adding a NEW Nervepack feature, add a `toggles.conf` row and wire its
enforcement** (`np_enabled` guard for runtime/cron, install/remove for managed) —
see `CLAUDE.md` § "Feature toggles".
