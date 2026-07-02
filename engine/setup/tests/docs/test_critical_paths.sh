#!/usr/bin/env bash
# np-test: critical-paths | happy+failure
# Regression tests for engine/setup/np-path-check.py — the guard that keeps stale
# pre-engine/content-split path references (`setup/x` instead of `engine/setup/x`)
# out of the docs and skills a fresh install follows.
#
# Asserts the checker BITES (STALE + MISSING both exit 1 with the right label),
# honors its exclusions (tests/ fixtures, historical plans, append-only log.md,
# and `dir/onboard` subdirs), AND that the real engine tree is clean (exit 0).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
NP="$(cd "$SETUP/../.." && pwd)"
CHECK="$SETUP/np-path-check.py"

fail() { echo "FAIL: $*"; exit 1; }

[[ -f "$CHECK" ]] || fail "checker not found at $CHECK"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# --- Case 1: STALE — a bare `setup/x` reference (missing engine/) is caught. ---
d1="$tmp/stale"; mkdir -p "$d1"
printf 'Run `setup/40-sync-nervepack.sh` to sync.\n' > "$d1/doc.md"
out1="$(python3 "$CHECK" "$d1" 2>&1)" && rc1=0 || rc1=$?
[[ $rc1 -eq 1 ]] || fail "Case 1: expected exit 1 on a stale path, got $rc1; output: $out1"
grep -q "STALE" <<<"$out1" || fail "Case 1: STALE not reported; output: $out1"
grep -q "40-sync-nervepack.sh" <<<"$out1" || fail "Case 1: token not named; output: $out1"
echo "  Case 1 OK: bare setup/ reference flagged STALE"

# --- Case 2: MISSING — an engine/-prefixed path to a nonexistent file is caught. ---
d2="$tmp/missing"; mkdir -p "$d2"
printf 'See `engine/setup/does-not-exist-xyz.sh` for details.\n' > "$d2/doc.md"
out2="$(python3 "$CHECK" "$d2" 2>&1)" && rc2=0 || rc2=$?
[[ $rc2 -eq 1 ]] || fail "Case 2: expected exit 1 on a missing target, got $rc2; output: $out2"
grep -q "MISSING" <<<"$out2" || fail "Case 2: MISSING not reported; output: $out2"
echo "  Case 2 OK: engine/setup/ path to nonexistent file flagged MISSING"

# --- Case 3: clean — a correct engine/-prefixed path to a real script passes. ---
d3="$tmp/clean"; mkdir -p "$d3"
# np-doctor.sh exists under the real engine root, which the checker always adds as
# a resolution root. Also include prose ("setup/teardown") that must NOT be flagged.
printf 'Verify with `engine/setup/np-doctor.sh`. The setup/teardown cycle is separate.\n' > "$d3/doc.md"
out3="$(python3 "$CHECK" "$d3" 2>&1)" && rc3=0 || rc3=$?
[[ $rc3 -eq 0 ]] || fail "Case 3: expected exit 0 on a clean doc, got $rc3; output: $out3"
echo "  Case 3 OK: correct engine/setup/ path passes; prose not flagged"

# --- Case 4: exclusions — historical/fixture/subdir contexts are not flagged. ---
d4="$tmp/excl"; mkdir -p "$d4/tests" "$d4/docs/superpowers/plans"
printf 'bad `setup/x.sh`\n'  > "$d4/tests/t.md"                      # tests/ fixture
printf 'bad `setup/y.sh`\n'  > "$d4/docs/superpowers/plans/p.md"     # historical plan
printf 'bad `setup/z.sh`\n'  > "$d4/log.md"                          # append-only log
printf 'ok `tests/onboard/test_mcp_install.sh`\n' > "$d4/sub.md"     # onboard as a subdir
out4="$(python3 "$CHECK" "$d4" 2>&1)" && rc4=0 || rc4=$?
[[ $rc4 -eq 0 ]] || fail "Case 4: exclusions should yield exit 0, got $rc4; output: $out4"
echo "  Case 4 OK: tests/, plans/, log.md, and dir/onboard subdir all excluded"

# --- Case 5: the guard — the real engine tree must be clean. ---
out5="$(python3 "$CHECK" "$NP" 2>&1)" && rc5=0 || rc5=$?
[[ $rc5 -eq 0 ]] || fail "Case 5: the engine tree has stale/broken path references:\n$out5"
echo "  Case 5 OK: real engine tree is clean"

echo "PASS test_critical_paths"
