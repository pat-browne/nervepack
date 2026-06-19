#!/usr/bin/env bash
# np_param must resolve skills.* + cap_bytes params from toggles.conf, and a
# toggles.local override must win.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../../np-toggle-lib.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/toggles.conf" <<'CONF'
memory|shared|runtime|on|cap_bytes=48000
evaluator|shared|runtime|on|cap_bytes=32000
skills|shared|runtime|on|split_kb=8,soft_kb=6,catalog_tok=4000,max_per_run=2
CONF

export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
source "$LIB"

[[ "$(np_param skills.split_kb 99)"   == "8" ]]     || { echo "FAIL: split_kb"; exit 1; }
[[ "$(np_param skills.max_per_run 99)" == "2" ]]    || { echo "FAIL: max_per_run"; exit 1; }
[[ "$(np_param memory.cap_bytes 0)"   == "48000" ]] || { echo "FAIL: memory cap"; exit 1; }
[[ "$(np_param evaluator.cap_bytes 0)" == "32000" ]] || { echo "FAIL: evaluator cap"; exit 1; }
[[ "$(np_param skills.nope 7)"        == "7" ]]     || { echo "FAIL: default fallback"; exit 1; }

printf 'skills.split_kb = 5\n' > "$tmp/local"
[[ "$(np_param skills.split_kb 99)"   == "5" ]]     || { echo "FAIL: local override"; exit 1; }
echo "PASS test_toggle_params"
