#!/usr/bin/env bash
# Test np-hook-lib.sh's Windows hook shim (NP_HOOK_WRAP). Claude Code on Windows runs
# hook commands via PowerShell, which can't execute a bare `~/...sh &` string, so on a
# Git-for-Windows host the registered command is routed through bash. Asserts: with
# wrap on, the stored command is `bash -lc '<original>'` (and dedup-by-basename still
# works); with wrap off (the Linux/macOS default), the command is stored verbatim —
# i.e. existing hosts are byte-for-byte unchanged.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../../np-hook-lib.sh"
fail=0
chk() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }

command -v jq >/dev/null || { echo "PASS test_hook_lib_win_wrap (skipped — jq missing)"; exit 0; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export CLAUDE_SETTINGS="$TMP/settings.json"
cmd_at() { jq -r '.hooks.SessionStart[0].hooks[0].command' "$CLAUDE_SETTINGS"; }

# --- wrap ON: command routed through Git-bash ---
( source "$LIB"; NP_HOOK_WRAP=1 np_register_hook SessionStart '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &' ) >/dev/null
chk "wrapped command runs through bash -lc" "[ \"\$(cmd_at)\" = \"bash -lc '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &'\" ]"
# dedup-by-basename still resolves through the wrapper: re-register => still exactly one
( source "$LIB"; NP_HOOK_WRAP=1 np_register_hook SessionStart '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &' ) >/dev/null
chk "wrap is idempotent (basename dedup sees through the wrapper)" \
  "[ \"\$(jq '[.hooks.SessionStart[].hooks[].command] | length' \"\$CLAUDE_SETTINGS\")\" = 1 ]"

# --- wrap OFF (default): verbatim, existing hosts unchanged ---
rm -f "$CLAUDE_SETTINGS"
( source "$LIB"; NP_HOOK_WRAP=0 np_register_hook SessionStart '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &' ) >/dev/null
chk "unwrapped command stored verbatim" "[ \"\$(cmd_at)\" = '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &' ]"

# --- default (no NP_HOOK_WRAP) on this Linux box auto-resolves to OFF ---
rm -f "$CLAUDE_SETTINGS"
( source "$LIB"; np_register_hook SessionStart '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &' ) >/dev/null
chk "auto-detect off on a non-Windows host (verbatim)" "[ \"\$(cmd_at)\" = '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &' ]"

[ $fail -eq 0 ] && echo "PASS test_hook_lib_win_wrap" || { echo "FAIL test_hook_lib_win_wrap"; exit 1; }
