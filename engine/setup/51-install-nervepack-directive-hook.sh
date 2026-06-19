#!/usr/bin/env bash
# Register a SessionStart hook in ~/.claude/settings.json that injects the
# "consult nervepack first" directive (setup/nervepack-session-directive.sh) into every
# Claude Code session's context.
#
# This is the companion to 50-install-session-hook.sh:
#   50 → registers the background git-sync (silent; writes a status file)
#   51 → registers the directive injector (synchronous; writes to context)
# Both are SessionStart hooks; they coexist in the SessionStart array.
#
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionStart '~/Code/nervepack/engine/setup/nervepack-session-directive.sh'
echo "To remove: edit $NP_SETTINGS and drop the matching SessionStart entry."
