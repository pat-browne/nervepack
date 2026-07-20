#!/usr/bin/env bash
# Register the resume-pointer hooks in ~/.claude/settings.json:
#   SessionStart      -> reconstruct the pointer for the most-recent completed
#                        PRIOR session (backgrounded so it never delays start)
#   UserPromptSubmit  -> surface a stale pointer + throttled live write for the
#                        current session
# Both hooks are Python (dispatched via engine/nervepack_engine/cli.py) as of the
# bash->Python resume-pointer port; np-resume-sessionstart.sh/np-resume-recall.sh
# no longer exist.
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionStart     'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook resume-sessionstart &'
np_register_hook UserPromptSubmit 'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook resume-recall'

echo "To remove: edit $NP_SETTINGS and drop the matching entries."
