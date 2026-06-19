#!/usr/bin/env bash
# np-test: knowledge-capture | failure
# episodic-scrub.sh is a fail-open stdin->stdout secret redactor. Bad / degenerate
# input (empty, binary garbage, no trailing newline) must NOT crash the pipeline
# (runs under `set -euo pipefail`) — it must exit 0 and still not leak a secret.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRUB="$HERE/../../episodic-scrub.sh"

[[ -x "$SCRUB" ]] || { echo "FAIL: scrub not executable: $SCRUB"; exit 1; }

# 1. Empty input -> clean exit, empty output.
if out="$(printf '' | bash "$SCRUB")"; then :; else echo "FAIL: empty input crashed (exit $?)"; exit 1; fi
[[ -z "$out" ]] || { echo "FAIL: empty input produced output: $out"; exit 1; }

# 2. Binary / garbage input -> must not crash the pipeline.
if head -c 4096 /dev/urandom | bash "$SCRUB" >/dev/null 2>&1; then :; else
  echo "FAIL: binary input crashed scrub (exit $?)"; exit 1
fi

# 3. No trailing newline, secret present -> still redacted, still exit 0.
if out="$(printf 'no newline sk-ABCDEFGHIJKLMNOPQRSTUV' | bash "$SCRUB")"; then :; else
  echo "FAIL: no-newline input crashed (exit $?)"; exit 1
fi
echo "$out" | grep -q 'REDACTED' || { echo "FAIL: secret not redacted in no-newline input: $out"; exit 1; }
echo "$out" | grep -q 'sk-ABCDEFG' && { echo "FAIL: raw secret leaked: $out"; exit 1; }

# 4. A pathological line of nothing-but-equals (regex backtracking bait) -> no hang/crash.
if printf '%s\n' "$(printf '=%.0s' {1..500})" | bash "$SCRUB" >/dev/null 2>&1; then :; else
  echo "FAIL: pathological input crashed (exit $?)"; exit 1
fi

echo "PASS test_scrub_failure"
