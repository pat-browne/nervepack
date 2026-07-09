#!/usr/bin/env bash
# Register the resume-pointer hooks in ~/.claude/settings.json:
#   SessionStart      -> reconstruct the pointer for the most-recent completed
#                        PRIOR session (backgrounded so it never delays start)
#   UserPromptSubmit  -> surface a stale pointer + throttled live write for the
#                        current session
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionStart     '~/Code/nervepack/engine/setup/np-resume-sessionstart.sh &'
np_register_hook UserPromptSubmit '~/Code/nervepack/engine/setup/np-resume-recall.sh'

echo "To remove: edit $NP_SETTINGS and drop the matching entries."
