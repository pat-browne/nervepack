#!/usr/bin/env bash
# Register three episodic hooks in ~/.claude/settings.json:
#   SessionEnd        → capture a session-end note
#   PreCompact        → capture a checkpoint note before the window compacts
#   UserPromptSubmit  → inject matching episodic themes on opening prompts
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionEnd       '~/Code/nervepack/engine/setup/episodic-capture.sh session-end'
np_register_hook PreCompact       '~/Code/nervepack/engine/setup/episodic-capture.sh checkpoint'
np_register_hook UserPromptSubmit '~/Code/nervepack/engine/setup/episodic-recall.sh'

echo "To remove: edit $NP_SETTINGS and drop the matching entries."
