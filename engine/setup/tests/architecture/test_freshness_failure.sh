#!/usr/bin/env bash
# np-test: architecture-freshness | failure
# Failure path for np-architecture-freshness.sh when its input is missing. The
# script's documented contract (its own header) is "advisory, exit 0 ALWAYS": a
# missing ARCHITECTURE.md is not an error, it prints a single explanatory line
#     architecture-freshness: ARCHITECTURE.md missing at <path>
# and exits 0 — it must NOT crash, and must NOT emit any STALE drift lines (it
# cannot reason about drift with no map). Black-box via the ARCH_* env overrides
# so the real repo map is never touched. Guards against a regression that lets a
# missing map abort the daily skill-maintain run (np_skill_maintain.py) it is invoked from.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$HERE/../../np-architecture-freshness.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# Point ARCH_FILE at a path that does not exist; give it a real (populated)
# toggles.conf + specs dir so that, IF the missing-map guard regressed and the
# script fell through, it WOULD emit STALE lines we'd then catch.
cat > "$tmp/toggles.conf" <<'EOF'
memory|shared|runtime|on|
newthing|shared|runtime|on|
EOF
mkdir -p "$tmp/specs"; : > "$tmp/specs/2026-01-01-newthing-design.md"
missing="$tmp/NOPE/ARCHITECTURE.md"   # parent dir absent too

rc=0
out="$(ARCH_FILE="$missing" ARCH_TOGGLES="$tmp/toggles.conf" ARCH_SPECS_DIR="$tmp/specs" bash "$CHECK")" || rc=$?
[[ "$rc" == 0 ]] || { echo "FAIL: advisory check exited $rc (want 0) on missing map: $out"; exit 1; }
echo "$out" | grep -q "ARCHITECTURE.md missing at $missing" \
  || { echo "FAIL: missing the documented 'ARCHITECTURE.md missing' line; got: $out"; exit 1; }
echo "$out" | grep -q 'STALE:' \
  && { echo "FAIL: emitted drift lines despite no map to compare against: $out"; exit 1; }
echo "PASS test_freshness_failure"
