#!/usr/bin/env bash
# np-suggestion-resolve.sh: append a suggestion to the resolved ledger (deduped,
# case/space-insensitive), error on empty input. (NP_RESOLVE_NO_BUILD avoids the
# metrics.js rebuild side-effect during the test.)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
RESOLVE="$SETUP/np-suggestion-resolve.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
L="$tmp/resolved.txt"
run() { NP_RESOLVED_SUGGESTIONS="$L" NP_RESOLVE_NO_BUILD=1 bash "$RESOLVE" "$@"; }

run "Promote auto-push rule" >/dev/null
# Lines now carry a trailing tab+ISO-timestamp (for retention pruning); match text portion only.
grep -q $'^Promote auto-push rule\t' "$L" || { echo "FAIL: suggestion not appended"; exit 1; }

# Idempotent: same suggestion in different case/spacing is not duplicated.
run "promote   AUTO-push rule" >/dev/null
cnt="$(grep -vcE '^#|^$' "$L")"
[[ "$cnt" -eq 1 ]] || { echo "FAIL: duplicate not deduped (count=$cnt)"; exit 1; }

# A genuinely different suggestion is appended.
run "Strengthen the directive" >/dev/null
[[ "$(grep -vcE '^#|^$' "$L")" -eq 2 ]] || { echo "FAIL: distinct suggestion not added"; exit 1; }

# Empty arg errors (non-zero), writes nothing.
set +e; run "" >/dev/null 2>&1; rc=$?; set -e
[[ $rc -ne 0 ]] || { echo "FAIL: empty arg should exit non-zero"; exit 1; }

echo "PASS test_suggestion_resolve"
