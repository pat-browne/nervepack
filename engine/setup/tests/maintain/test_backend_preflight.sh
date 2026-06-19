#!/usr/bin/env bash
# np-test: maintain-backend-preflight | preflight
# Backend-aware pre-flight (ARCHITECTURE invariant 13):
#   - claude backend without the binary → bail + exit 0
#   - local backend without NP_LLM_AGENT_CMD → bail + exit 0
# Tests both 76 and 77.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REFINE="$HERE/../../76-run-refine.sh"
COMPACT="$HERE/../../77-run-compact.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

fake_home="$tmp/home"
mkdir -p "$fake_home/.cache/nervepack"

export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
printf 'maintain|shared|runtime|on|\nmaintain.refine|shared|runtime|on|\nmaintain.compact|shared|runtime|on|\n' \
  > "$tmp/toggles.conf"
: > "$tmp/local"

refine_log="$tmp/refine.log"
compact_log="$tmp/compact.log"

check_bail() {   # $1=label  $2=logfile  $3=expected-fragment
  local label="$1" log="$2" frag="$3"
  [[ -s "$log" ]] || { echo "FAIL ($label): no bail log written"; exit 1; }
  grep -qi "$frag" "$log" \
    || { echo "FAIL ($label): log missing '$frag': $(cat "$log")"; exit 1; }
}

# --- claude backend, no binary ---
: > "$refine_log"; : > "$compact_log"
rc=0
HOME="$fake_home" CLAUDE_BIN="$tmp/no-such-claude" NP_LLM_BACKEND=claude \
  REFINE_LOG="$refine_log" bash "$REFINE" 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || { echo "FAIL (refine/claude-no-bin): must exit 0, got $rc"; exit 1; }
check_bail "refine/claude-no-bin" "$refine_log" "claude CLI not found"

: > "$compact_log"
rc=0
HOME="$fake_home" CLAUDE_BIN="$tmp/no-such-claude" NP_LLM_BACKEND=claude \
  COMPACT_LOG="$compact_log" bash "$COMPACT" 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || { echo "FAIL (compact/claude-no-bin): must exit 0, got $rc"; exit 1; }
check_bail "compact/claude-no-bin" "$compact_log" "claude CLI not found"

# --- local backend, no NP_LLM_AGENT_CMD ---
: > "$refine_log"
rc=0
HOME="$fake_home" NP_LLM_BACKEND=local \
  REFINE_LOG="$refine_log" bash "$REFINE" 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || { echo "FAIL (refine/local-no-cmd): must exit 0, got $rc"; exit 1; }
check_bail "refine/local-no-cmd" "$refine_log" "NP_LLM_AGENT_CMD"

: > "$compact_log"
rc=0
HOME="$fake_home" NP_LLM_BACKEND=local \
  COMPACT_LOG="$compact_log" bash "$COMPACT" 2>&1 || rc=$?
[[ "$rc" -eq 0 ]] || { echo "FAIL (compact/local-no-cmd): must exit 0, got $rc"; exit 1; }
check_bail "compact/local-no-cmd" "$compact_log" "NP_LLM_AGENT_CMD"

echo "PASS test_backend_preflight"
