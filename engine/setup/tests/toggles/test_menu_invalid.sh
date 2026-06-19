#!/usr/bin/env bash
# np-test: toggle-menu | failure
# Failure path for nervepack-toggle-menu.sh: invalid / out-of-range / empty input
# must be IGNORED (the menu loops via `continue`) and must NOT flip any feature.
# Asserts the concrete side effect: toggles.conf is byte-identical before/after,
# and both features remain `on`. Guards the input-validation branches
# ('' / *[!0-9]* / out-of-range index) against a regression that mis-parses a bad
# choice into a real toggle write.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MENU="$HERE/../../nervepack-toggle-menu.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/toggles.conf" <<'C'
memory|shared|runtime|on|
playbooks|shared|runtime|on|
C
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_TOGGLE_NO_COMMIT=1
before="$(cat "$tmp/toggles.conf")"

# Feed only invalid choices, then quit: 'x' (non-numeric), '99' (out of range),
# '0' (index -> -1, out of range), empty line, then 'q' to exit.
printf 'x\n99\n0\n\nq\n' | bash "$MENU" >/dev/null 2>&1 || true

after="$(cat "$tmp/toggles.conf")"
[[ "$before" == "$after" ]] || { echo "FAIL: invalid menu input mutated toggles.conf"; diff <(echo "$before") <(echo "$after"); exit 1; }
awk -F'|' '$1=="memory"{print $4}'    "$tmp/toggles.conf" | grep -qx 'on' || { echo "FAIL: memory no longer on"; exit 1; }
awk -F'|' '$1=="playbooks"{print $4}' "$tmp/toggles.conf" | grep -qx 'on' || { echo "FAIL: playbooks no longer on"; exit 1; }
# No local override file should have been created either (no toggle call ran).
[[ ! -s "$tmp/local" ]] || { echo "FAIL: a local override was written for an invalid choice"; cat "$tmp/local"; exit 1; }
echo "PASS test_menu_invalid"
