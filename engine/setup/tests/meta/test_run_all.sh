#!/usr/bin/env bash
# np-test: test-runner | happy
# Proves run-all.sh aggregates child results: green when all pass, red when one
# fails, and the --report output carries correct counts. Uses throwaway fixture
# tests in a temp tree so it never depends on the real suite.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$HERE/../run-all.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/tests/alpha" "$tmp/tests/beta"
cat > "$tmp/tests/alpha/test_ok.sh"  <<'T'
#!/usr/bin/env bash
echo "PASS test_ok"
T
cat > "$tmp/tests/alpha/test_ok2.py" <<'T'
import sys; print("ok"); sys.exit(0)
T
cat > "$tmp/tests/beta/test_bad.sh" <<'T'
#!/usr/bin/env bash
echo "FAIL: intentional"; exit 1
T

report="$tmp/report.md"
set +e
NP_TESTS_ROOT="$tmp/tests" bash "$RUNNER" --report "$report" >"$tmp/out" 2>&1
code=$?
set -e

[[ $code -ne 0 ]] || { echo "FAIL: runner exited 0 despite a failing child"; cat "$tmp/out"; exit 1; }
grep -q "2 passed" "$report" || { echo "FAIL: report missing '2 passed'"; cat "$report"; exit 1; }
grep -q "1 failed" "$report" || { echo "FAIL: report missing '1 failed'"; cat "$report"; exit 1; }
grep -q "alpha" "$report"   || { echo "FAIL: report missing 'alpha' functionality group"; cat "$report"; exit 1; }

rm -rf "$tmp/tests/beta"
set +e
NP_TESTS_ROOT="$tmp/tests" bash "$RUNNER" >"$tmp/out2" 2>&1
code2=$?
set -e
[[ $code2 -eq 0 ]] || { echo "FAIL: runner exited nonzero with all-passing children"; cat "$tmp/out2"; exit 1; }

echo "PASS test_run_all"
