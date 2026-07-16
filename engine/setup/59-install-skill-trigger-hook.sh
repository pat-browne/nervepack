#!/usr/bin/env bash
# Register skill-trigger-recall.sh as a UserPromptSubmit hook.
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook UserPromptSubmit 'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook skill-trigger-recall'
echo "To remove: edit $NP_SETTINGS and drop the matching entry."
