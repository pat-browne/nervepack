#!/usr/bin/env bash
# np-test: maintain-toggle-gate | gating
# 77-run-compact.sh must exit 0 without acting when its toggle is disabled, and
# must not skip when enabled. (refine's toggle gate is covered in Python by
# tests/maintain/test_np_refine.py since 76-run-refine.sh was retired.)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPACT="$HERE/../../77-run-compact.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
: > "$tmp/toggles.conf"

# --- 77-run-compact.sh ---

# OFF: toggle guard fires, prints skip, exits 0
printf 'maintain.compact=off\n' > "$tmp/local"
out_off="$(bash "$COMPACT" 2>&1 || true)"
echo "$out_off" | grep -qiE 'skipped: maintain.compact disabled' \
  || { echo "FAIL (compact): guard did not skip while off: $out_off"; exit 1; }

# ON: no skip message
printf 'maintain.compact=on\n' > "$tmp/local"
out_on="$(bash "$COMPACT" 2>&1 || true)"
echo "$out_on" | grep -qiE 'skipped: maintain.compact disabled' \
  && { echo "FAIL (compact): guard skipped while on: $out_on"; exit 1; }

echo "PASS test_toggle_gating"
