#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MENU="$HERE/../../nervepack-toggle-menu.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/toggles.conf" <<'C'
memory|shared|runtime|on|
playbooks|shared|runtime|on|
C
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_TOGGLE_NO_COMMIT=1
# feed: toggle item 1 (memory), then save+quit
printf '1\ns\n' | bash "$MENU" >/dev/null 2>&1 || true
awk -F'|' '$1=="memory"{print $4}' "$tmp/toggles.conf" | grep -q '^off$' || { echo "FAIL: menu did not flip memory"; exit 1; }
echo "PASS test_menu"
