#!/usr/bin/env bash
# Register the SessionStart back-capture sweep in ~/.claude/settings.json.
# Backgrounded (`&`) so it never delays session start. This is the reliable
# capture path: SessionEnd `claude -p` hooks get killed before completing and
# `/exit` doesn't fire SessionEnd at all (see np-backcapture-sweep.sh header).
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

# Backgrounded (`&`) so it never delays session start — but `&` alone does NOT
# detach: the child inherits the hook's stdout pipe and Claude Code reads it to EOF,
# so without the stdout+stderr redirect a minutes-long sweep blocks session start.
np_register_hook SessionStart '~/Code/nervepack/engine/setup/np-backcapture-sweep.sh >/dev/null 2>&1 &'

echo "To remove: edit $NP_SETTINGS and drop the matching entry."
