#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/toggles.conf" <<'C'
memory|shared|runtime|on|
playbooks|shared|runtime|off|
sync|shared|runtime|on|interval=86400
allowlist|local|managed|on|
C
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
source "$HERE/../../np-toggle-lib.sh"

np_enabled memory          || { echo "FAIL: memory should be on"; exit 1; }
np_enabled playbooks       && { echo "FAIL: playbooks should be off"; exit 1; }
np_enabled memory.capture  || { echo "FAIL: sub inherits family on"; exit 1; }
np_enabled missingfeature  || { echo "FAIL: unknown should fail-open on"; exit 1; }

echo "memory=off" > "$tmp/local"
np_enabled memory          && { echo "FAIL: local override off ignored"; exit 1; }
np_enabled memory.recall   && { echo "FAIL: sub should inherit local family off"; exit 1; }
echo "memory.recall=on" >> "$tmp/local"
np_enabled memory.recall   || { echo "FAIL: explicit sub override on ignored"; exit 1; }

[[ "$(np_param sync.interval 999)" == "86400" ]] || { echo "FAIL: conf param"; exit 1; }
echo "sync.interval=3600" >> "$tmp/local"
[[ "$(np_param sync.interval 999)" == "3600" ]]  || { echo "FAIL: local param override"; exit 1; }
[[ "$(np_param no.such 42)" == "42" ]]           || { echo "FAIL: param default"; exit 1; }
echo "PASS test_lib"
