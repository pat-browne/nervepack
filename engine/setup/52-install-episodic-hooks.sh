#!/usr/bin/env bash
# Register three episodic hooks in ~/.claude/settings.json:
#   SessionEnd        → capture a session-end note (bash-free: cli.py hook episodic-capture)
#   PreCompact        → capture a checkpoint note before the window compacts (same dispatch)
#   UserPromptSubmit  → inject matching episodic themes on opening prompts
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
#
# SessionEnd is backgrounded (trailing `&`, same pattern as 40-sync-nervepack.sh):
# Claude Code does not await SessionEnd hooks and reports a killed one as "Hook
# cancelled" (invariant 12). The backgrounded call returns near-instantly so the
# hook itself is never flagged as cancelled; actual capture still relies on
# np-backcapture-sweep.sh at the next SessionStart as the reliable path — this
# just stops a doomed synchronous attempt from surfacing as a user-visible failure.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionEnd       'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook episodic-capture session-end &'
np_register_hook PreCompact       'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook episodic-capture checkpoint'
np_register_hook UserPromptSubmit 'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook episodic-recall'

echo "To remove: edit $NP_SETTINGS and drop the matching entries."
