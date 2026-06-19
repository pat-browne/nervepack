#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI="$HERE/../../nervepack-toggle.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/toggles.conf" <<'C'
memory|shared|runtime|on|
allowlist|local|managed|on|
sync|shared|runtime|on|interval=86400
C
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_TOGGLE_NO_COMMIT=1 NP_TOGGLE_NO_MANAGED=1
run() { bash "$CLI" "$@"; }

# local feature -> writes local file
run allowlist off >/dev/null
grep -q '^allowlist=off' "$tmp/local" || { echo "FAIL: local flip not written"; exit 1; }

# shared feature -> edits conf state column
run memory off >/dev/null
awk -F'|' '$1=="memory"{print $4}' "$tmp/toggles.conf" | grep -q '^off$' || { echo "FAIL: shared flip not in conf"; exit 1; }

# param
run param sync.interval 3600 >/dev/null
[[ "$(NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"; source "$HERE/../../np-toggle-lib.sh"; np_param sync.interval 1)" == "3600" ]] || { echo "FAIL: param not set"; exit 1; }

# status lists features with state (capture first; `| grep -q` + pipefail SIGPIPEs the producer)
out="$(run status)"
echo "$out" | grep -qiE 'memory.*off' || { echo "FAIL: status missing memory off"; echo "$out"; exit 1; }
echo "PASS test_cli"
