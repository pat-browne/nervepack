#!/usr/bin/env bash
# Register the SessionStart/SessionEnd hooks in ~/.claude/settings.json that
# auto-pull ~/Code/nervepack in the background and refresh + open the
# performance dashboard (cli.py-dispatched) at the start of every Claude Code
# session.
#
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
# Uses jq for JSON editing; falls back to a clear error if jq is missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

# SessionStart = throttled backup; SessionEnd = primary (always sync on exit).
# Backgrounded hooks MUST redirect stdout+stderr: a `&` child inherits the hook's
# stdout pipe and holds it open, and Claude Code reads that pipe to EOF — so without
# the redirect it blocks session start until the child exits (the `&` alone does NOT
# detach). See np-kb-claude-headless-scripting.
np_register_hook SessionStart '~/Code/nervepack/engine/setup/40-sync-nervepack.sh >/dev/null 2>&1 &'
np_register_hook SessionEnd   '~/Code/nervepack/engine/setup/40-sync-nervepack.sh exit >/dev/null 2>&1 &'
# SessionStart = refresh metrics + open the performance dashboard (gated by evaluator.dashboard).
np_register_hook SessionStart 'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook open-dashboard >/dev/null 2>&1 &'
echo "To remove: edit $NP_SETTINGS and drop the matching SessionStart/SessionEnd entries."
