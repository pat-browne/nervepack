#!/usr/bin/env bash
# np-test: 51-install-nervepack-directive-hook | happy
# 51-install-nervepack-directive-hook.sh registers the cli.py hook session-directive
# dispatch as a SessionStart hook (synchronous; injects the directive into context).
# Happy: the command lands in a temp settings.json under SessionStart.
# Idempotency: a second run does NOT duplicate the entry.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../51-install-nervepack-directive-hook.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"; echo '{}' > "$CLAUDE_SETTINGS"

bash "$INSTALL" >/dev/null
bash "$INSTALL" >/dev/null   # idempotent

n="$(jq '[.hooks.SessionStart[].hooks[] | select(.command|test("cli\\.py hook session-directive"))] | length' "$CLAUDE_SETTINGS")"
[[ "$n" == "1" ]] || { echo "FAIL: directive SessionStart count=$n (want 1)"; exit 1; }
jq -e '[.hooks.SessionStart[].hooks[].command] | any(test("cli\\.py hook session-directive$"))' "$CLAUDE_SETTINGS" >/dev/null \
  || { echo "FAIL: directive command wrong (expected no trailing &, synchronous)"; exit 1; }
echo "PASS test_install_directive_hook"
