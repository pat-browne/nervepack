#!/usr/bin/env bash
# Register the SessionEnd performance-evaluator hook (bash-free: cli.py hook
# evaluator). Idempotent: re-running after a script path change REPLACES the
# stale entry (np-hook-lib.sh).
#
# Backgrounded (trailing `&`, same pattern as 40-sync-nervepack.sh / the episodic
# SessionEnd hook): Claude Code does not await SessionEnd hooks and reports a
# killed one as "Hook cancelled" (invariant 12) — backgrounding returns fast
# enough to avoid that report. np-backcapture-sweep.sh remains the reliable
# capture path at the next SessionStart.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook SessionEnd 'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook evaluator &'
