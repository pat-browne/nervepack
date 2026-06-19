#!/usr/bin/env bash
# Remove exactly the Nervepack-managed allowlist entries (allowlist-entries.txt)
# from settings.json, leaving any hand-added rules intact. Idempotent.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
ENTRIES="$HERE/allowlist-entries.txt"
command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }
[[ -f "$SETTINGS" && -f "$ENTRIES" ]] || exit 0
managed="$(jq -R -s 'split("\n") | map(select(length>0))' "$ENTRIES")"
tmp=$(mktemp)
jq --argjson m "$managed" '
  .permissions.allow = ((.permissions.allow // []) - $m)
' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
echo "Removed Nervepack-managed allowlist entries from $SETTINGS"
