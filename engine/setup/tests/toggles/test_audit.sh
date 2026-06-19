#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT="$HERE/../../nervepack-toggle-audit.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" CLAUDE_SETTINGS="$tmp/settings.json"
printf 'memory|shared|runtime|on|\n' > "$tmp/toggles.conf"
# a hook referencing a nervepack script with NO matching family in the manifest
jq -n '{hooks:{PreToolUse:[{matcher:"Bash",hooks:[{type:"command",command:"~/Code/nervepack/setup/widget-guard.sh"}]}]}}' > "$CLAUDE_SETTINGS"
out="$(bash "$AUDIT" 2>&1 || true)"
echo "$out" | grep -qi 'widget-guard' || { echo "FAIL: audit did not flag unmanaged hook: $out"; exit 1; }
echo "PASS test_audit"
