#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOVE="$HERE/../../91-remove-claude-permissions.sh"
ENTRIES="$HERE/../../allowlist-entries.txt"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"
m1="$(head -1 "$ENTRIES")"; m2="$(sed -n '2p' "$ENTRIES")"
jq -n --arg a "$m1" --arg b "$m2" '{permissions:{allow:[$a,$b,"Bash(my-own-tool:*)"]}}' > "$CLAUDE_SETTINGS"
bash "$REMOVE" >/dev/null
jq -e '.permissions.allow | index("Bash(my-own-tool:*)")' "$CLAUDE_SETTINGS" >/dev/null || { echo "FAIL: hand-added rule removed"; exit 1; }
jq -e --arg a "$m1" '.permissions.allow | index($a)' "$CLAUDE_SETTINGS" >/dev/null && { echo "FAIL: managed entry not removed"; exit 1; }
echo "PASS test_allowlist"
