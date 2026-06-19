#!/usr/bin/env bash
# Register a SessionStart hook in ~/.claude/settings.json that auto-pulls
# ~/Code/nervepack in the background at the start of every Claude Code session.
#
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
# Uses jq for JSON editing; falls back to a clear error if jq is missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

# SessionStart = throttled backup; SessionEnd = primary (always sync on exit).
np_register_hook SessionStart '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &'
np_register_hook SessionEnd   '~/Code/nervepack/engine/setup/40-sync-nervepack.sh exit &'
# SessionStart = refresh metrics + open the performance dashboard (gated by evaluator.dashboard).
np_register_hook SessionStart '~/Code/nervepack/engine/setup/74-open-dashboard.sh &'
echo "To remove: edit $NP_SETTINGS and drop the matching SessionStart/SessionEnd entries."
