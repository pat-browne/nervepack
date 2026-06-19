#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../54-install-evaluator-hook.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/s.json"; echo '{}' > "$CLAUDE_SETTINGS"
bash "$INSTALL" >/dev/null; bash "$INSTALL" >/dev/null  # idempotent
n="$(jq '[.hooks.SessionEnd[].hooks[] | select(.command|test("np-evaluator.sh"))] | length' "$CLAUDE_SETTINGS")"
[[ "$n" == "1" ]] || { echo "FAIL: evaluator SessionEnd count=$n"; exit 1; }
echo "PASS test_install_hook"
