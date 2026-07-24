#!/usr/bin/env bash
# Register the open-artifact PostToolUse hook: when a Write call creates a
# spec/plan doc under docs/superpowers/{specs,plans}/*.md, open it with the OS
# default handler so a human's attention actually lands on it. Matcher scopes
# it to the Write tool only (see np-hook-lib.sh for the matcher param).
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (np-hook-lib.sh register-by-basename).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

np_register_hook PostToolUse 'python3 ~/Code/nervepack/engine/nervepack_engine/cli.py hook open-artifact' 'Write'

echo "To remove: edit $NP_SETTINGS and drop the matching entry."
