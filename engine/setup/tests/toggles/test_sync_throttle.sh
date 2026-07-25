#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC="$HERE/../../np_sync.py"          # phase 17: 40-sync-nervepack.sh retired
command -v python3 >/dev/null 2>&1 || { echo "SKIP test_sync_throttle: no python3"; exit 0; }
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_SYNC_STAMP="$tmp/last-sync"
printf 'sync|shared|runtime|on|interval=86400\n' > "$tmp/toggles.conf"
export NP_SYNC_DRYRUN=1
# backup mode + fresh stamp -> within interval -> skip
date +%s > "$NP_SYNC_STAMP"
out="$(python3 "$SYNC" backup 2>&1 || true)"
echo "$out" | grep -qiE 'skip|within|throttle' || { echo "FAIL: backup did not throttle: $out"; exit 1; }
# exit mode + fresh stamp -> ALWAYS sync (no throttle)
out_exit="$(python3 "$SYNC" exit 2>&1 || true)"
echo "$out_exit" | grep -qiE 'would sync|sync now' || { echo "FAIL: exit mode throttled: $out_exit"; exit 1; }
# sync off -> skip in any mode
echo "sync=off" > "$tmp/local"; rm -f "$NP_SYNC_STAMP"
out2="$(python3 "$SYNC" exit 2>&1 || true)"
echo "$out2" | grep -qiE 'disabled|off' || { echo "FAIL: did not honor sync=off: $out2"; exit 1; }
echo "PASS test_sync_throttle"
