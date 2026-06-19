#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$HERE/../../72-run-episodic-maintain.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
: > "$tmp/toggles.conf"

# OFF -> the toggle guard fires and prints a skip message, exits early
echo "memory.maintain=off" > "$tmp/local"
out_off="$(bash "$W" 2>&1 || true)"
echo "$out_off" | grep -qiE 'skipped: memory.maintain disabled' || { echo "FAIL: guard did not skip while off: $out_off"; exit 1; }

# ON -> the guard does NOT skip (wrapper proceeds to its own logic; no toggle-skip line)
echo "memory.maintain=on" > "$tmp/local"
out_on="$(bash "$W" 2>&1 || true)"
echo "$out_on" | grep -qiE 'skipped: memory.maintain disabled' && { echo "FAIL: guard skipped while on: $out_on"; exit 1; }
echo "PASS test_cron_guards"
