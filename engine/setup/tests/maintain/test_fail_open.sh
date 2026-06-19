#!/usr/bin/env bash
# np-test: maintain-fail-open | fail-open
# With the model backend unavailable (claude binary missing, NP_LLM_BACKEND=claude),
# 76-run-refine.sh and 77-run-compact.sh must bail (log a message) and exit 0.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REFINE="$HERE/../../76-run-refine.sh"
COMPACT="$HERE/../../77-run-compact.sh"
NP="$(cd "$HERE/../../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# Use a fake home so log dirs are sandboxed.
fake_home="$tmp/home"
mkdir -p "$fake_home/.cache/nervepack"

# Enable toggles (default-on, but set explicitly).
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
printf 'maintain|shared|runtime|on|\nmaintain.refine|shared|runtime|on|\nmaintain.compact|shared|runtime|on|\n' \
  > "$tmp/toggles.conf"
: > "$tmp/local"

# Point at a non-existent claude binary → backend unavailable.
MISSING_CLAUDE="$tmp/no-such-claude"

refine_log="$tmp/refine.log"
compact_log="$tmp/compact.log"

# --- 76-run-refine.sh fail-open ---
rc=0
HOME="$fake_home" CLAUDE_BIN="$MISSING_CLAUDE" NP_LLM_BACKEND=claude \
  REFINE_LOG="$refine_log" bash "$REFINE" 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || { echo "FAIL (refine): must exit 0 when backend unavailable, got $rc"; exit 1; }
[[ -s "$refine_log" ]] || { echo "FAIL (refine): no bail log written"; exit 1; }
grep -qi 'ERROR' "$refine_log" || { echo "FAIL (refine): bail log has no ERROR line: $(cat "$refine_log")"; exit 1; }

# --- 77-run-compact.sh fail-open ---
rc=0
HOME="$fake_home" CLAUDE_BIN="$MISSING_CLAUDE" NP_LLM_BACKEND=claude \
  COMPACT_LOG="$compact_log" bash "$COMPACT" 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || { echo "FAIL (compact): must exit 0 when backend unavailable, got $rc"; exit 1; }
[[ -s "$compact_log" ]] || { echo "FAIL (compact): no bail log written"; exit 1; }
grep -qi 'ERROR' "$compact_log" || { echo "FAIL (compact): bail log has no ERROR line: $(cat "$compact_log")"; exit 1; }

echo "PASS test_fail_open"
