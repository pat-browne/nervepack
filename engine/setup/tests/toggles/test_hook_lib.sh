#!/usr/bin/env bash
# Test np-hook-lib.sh: register-by-basename is idempotent AND migrates a path change
# (the regression behind the duplicate hooks the engine/ split left in settings.json).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../../np-hook-lib.sh"
fail=0
chk() { if eval "$2"; then echo "  ok   $1"; else echo "  FAIL $1"; fail=1; fi; }

command -v jq >/dev/null || { echo "PASS test_hook_lib (skipped — jq missing)"; exit 0; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export CLAUDE_SETTINGS="$TMP/settings.json"
# fresh source each time so NP_SETTINGS picks up the env
( source "$LIB"; np_register_hook SessionStart '~/Code/nervepack/setup/40-sync-nervepack.sh &' ) >/dev/null

count_cmd() { jq --arg s "$1" '[.hooks.SessionStart[].hooks[].command | select(contains($s))] | length' "$CLAUDE_SETTINGS"; }

chk "old-path entry registered" "[ \"\$(count_cmd '40-sync-nervepack.sh')\" = 1 ]"

# Re-run with the NEW (moved) path: must REPLACE, not duplicate.
( source "$LIB"; np_register_hook SessionStart '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &' ) >/dev/null
chk "still exactly one entry after path change (no duplicate)" "[ \"\$(count_cmd '40-sync-nervepack.sh')\" = 1 ]"
chk "the surviving entry uses the NEW engine/ path" "[ \"\$(count_cmd 'engine/setup/40-sync-nervepack.sh')\" = 1 ]"
chk "no stale old-path entry remains" "[ \"\$(jq '[.hooks.SessionStart[].hooks[].command | select(contains(\"nervepack/setup/40\"))] | length' \"\$CLAUDE_SETTINGS\")\" = 0 ]"

# Re-run identical: still one (pure idempotency).
( source "$LIB"; np_register_hook SessionStart '~/Code/nervepack/engine/setup/40-sync-nervepack.sh &' ) >/dev/null
chk "idempotent re-run keeps exactly one" "[ \"\$(count_cmd '40-sync-nervepack.sh')\" = 1 ]"

# A different script in the same event is independent (not removed).
( source "$LIB"; np_register_hook SessionStart '~/Code/nervepack/engine/setup/74-open-dashboard.sh &' ) >/dev/null
chk "different script coexists" "[ \"\$(count_cmd '74-open-dashboard.sh')\" = 1 ] && [ \"\$(count_cmd '40-sync-nervepack.sh')\" = 1 ]"

# matcher is preserved (PreToolUse Bash guard).
( source "$LIB"; np_register_hook PreToolUse '~/Code/nervepack/engine/setup/playbook-guard.sh' 'Bash' ) >/dev/null
chk "matcher preserved" "[ \"\$(jq -r '.hooks.PreToolUse[0].matcher' \"\$CLAUDE_SETTINGS\")\" = 'Bash' ]"

[ $fail -eq 0 ] && echo "PASS test_hook_lib" || { echo "FAIL test_hook_lib"; exit 1; }
