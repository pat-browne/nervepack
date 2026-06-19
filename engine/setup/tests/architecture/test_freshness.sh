#!/usr/bin/env bash
# Regression for np-architecture-freshness.sh: a feature in toggles.conf or a
# design spec that ISN'T referenced in ARCHITECTURE.md must be flagged STALE; a
# map that references everything must report 0 gaps. Black-box via the ARCH_*
# env overrides (no touching the real repo files).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$HERE/../../np-architecture-freshness.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/specs"
printf '%s\n' '{"x":1}' >/dev/null
cat > "$tmp/toggles.conf" <<'EOF'
# feature|scope|enforce|state|param
memory|shared|runtime|on|
newthing|shared|runtime|on|
EOF
: > "$tmp/specs/2026-01-01-newthing-design.md"

# 1. Map that references neither newthing feature nor its spec → 2 gaps.
cat > "$tmp/ARCH-stale.md" <<'EOF'
# map
The `memory` feature exists. See 1999-old-design.md.
EOF
out="$(ARCH_FILE="$tmp/ARCH-stale.md" ARCH_TOGGLES="$tmp/toggles.conf" ARCH_SPECS_DIR="$tmp/specs" bash "$CHECK")"
echo "$out" | grep -q "STALE: feature 'newthing'" || { echo "FAIL: missing feature not flagged"; echo "$out"; exit 1; }
echo "$out" | grep -q "STALE: spec '2026-01-01-newthing-design.md'" || { echo "FAIL: missing spec not flagged"; echo "$out"; exit 1; }
echo "$out" | grep -q 'architecture-freshness: 2 gap' || { echo "FAIL: expected 2 gaps, got: $(echo "$out"|tail -1)"; exit 1; }

# 2. Map that references both → 0 gaps.
cat > "$tmp/ARCH-fresh.md" <<'EOF'
# map
Features: `memory`, `newthing`.
Specs: 2026-01-01-newthing-design.md.
EOF
out="$(ARCH_FILE="$tmp/ARCH-fresh.md" ARCH_TOGGLES="$tmp/toggles.conf" ARCH_SPECS_DIR="$tmp/specs" bash "$CHECK")"
echo "$out" | grep -q 'architecture-freshness: 0 gap' || { echo "FAIL: expected 0 gaps, got: $(echo "$out"|tail -1)"; exit 1; }

echo "PASS test_freshness"
