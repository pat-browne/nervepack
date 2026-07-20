#!/usr/bin/env bash
# Register the SessionStart back-capture sweep in ~/.claude/settings.json.
# Dispatches through the nervepack Python CLI (bash-free — see
# engine/nervepack_engine/cli.py and hooks/backcapture_sweep.py). Backgrounded
# (`&`) so it never delays session start. This is the reliable capture path:
# SessionEnd `claude -p` hooks get killed before completing and `/exit` doesn't
# fire SessionEnd at all (see backcapture_sweep.py's module docstring).
# Idempotent: re-running after a path/command change REPLACES the stale entry
# instead of duplicating it (np-hook-lib.sh register-by-basename, extended to
# key CLI-dispatched hooks on "cli.py <group> <name>").
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

# Backgrounded (`&`) so it never delays session start — but `&` alone does NOT
# detach: the child inherits the hook's stdout pipe and Claude Code reads it to EOF,
# so without the stdout+stderr redirect a minutes-long sweep blocks session start.
np_register_hook SessionStart 'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook backcapture-sweep >/dev/null 2>&1 &'

echo "To remove: edit $NP_SETTINGS and drop the matching entry."
