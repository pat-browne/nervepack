#!/usr/bin/env bash
# np-test: nervepack-session-directive | failure
# Two fail-open paths for the SessionStart directive injector:
#   1. NERVEPACK_AGENT=1 set -> we are inside a nervepack sub-agent; bail with no
#      injection (exit 0, empty stdout) so the directive never recurses into agent
#      contexts (mirrors the guard in episodic-capture / np-session-flush).
#   2. directive markdown missing -> fail open (exit 0, no output) rather than
#      breaking session start.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="$HERE/../../nervepack-session-directive.sh"

# --- 1) NERVEPACK_AGENT guard: bail, no injection -------------------------
out="$(NERVEPACK_AGENT=1 bash "$DIR" 2>/dev/null)"; rc=$?
[[ "$rc" == "0" ]] || { echo "FAIL: NERVEPACK_AGENT=1 exit=$rc (want 0)"; exit 1; }
[[ -z "$out" ]] || { echo "FAIL: NERVEPACK_AGENT=1 still injected context: $out"; exit 1; }

# Control: without the guard, the same invocation DOES inject (proves the test
# isn't a tautology — the directive really fires when not inside an agent).
ctl="$(bash "$DIR" 2>/dev/null)"; crc=$?
[[ "$crc" == "0" ]] || { echo "FAIL: unguarded directive exit=$crc"; exit 1; }
[[ -n "$ctl" ]] || { echo "FAIL: unguarded directive produced no output (guard test would be vacuous)"; exit 1; }
echo "$ctl" | grep -q 'additionalContext' || { echo "FAIL: unguarded directive missing additionalContext"; exit 1; }

# --- 2) missing directive markdown: fail open ----------------------------
# Copy the script into a temp dir WITHOUT its companion .md so the [[ -f ]] guard
# fires; assert exit 0 and empty stdout (no crash, no injection).
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cp "$DIR" "$tmp/nervepack-session-directive.sh"
cp "$HERE/../../np-toggle-lib.sh" "$tmp/np-toggle-lib.sh"
# (intentionally NOT copying nervepack-session-directive.md)
out2="$(bash "$tmp/nervepack-session-directive.sh" 2>/dev/null)"; rc2=$?
[[ "$rc2" == "0" ]] || { echo "FAIL: missing md exit=$rc2 (want 0)"; exit 1; }
[[ -z "$out2" ]] || { echo "FAIL: missing md still produced output: $out2"; exit 1; }

echo "PASS test_directive_failure"
