#!/usr/bin/env bash
# Register the SessionEnd promotion-flush hook (drains inboxes -> committed layers
# on exit; crons become backup). Idempotent: re-running after a script path change
# REPLACES the stale entry (np-hook-lib.sh). Appends LAST so it runs after
# episodic-capture + np-evaluator have written this session to the inboxes.
# np-session-flush.sh (bash) is retired -- the hook is now the bash-free
# nervepack_engine.hooks.session_flush, dispatched via cli.py like every other
# ported hook. No trailing `&`: it backgrounds itself internally via
# subprocess.Popen(start_new_session=True), not at the settings.json level.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionEnd 'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook session-flush'
