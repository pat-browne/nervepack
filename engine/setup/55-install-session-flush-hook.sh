#!/usr/bin/env bash
# Register the SessionEnd promotion-flush hook (drains inboxes -> committed layers
# on exit; crons become backup). Idempotent: re-running after a script path change
# REPLACES the stale entry (np-hook-lib.sh). Appends LAST so it runs after
# episodic-capture + np-evaluator have written this session to the inboxes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionEnd '~/Code/nervepack/engine/setup/np-session-flush.sh'
