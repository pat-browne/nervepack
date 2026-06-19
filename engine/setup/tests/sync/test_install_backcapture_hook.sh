#!/usr/bin/env bash
# np-test: 56-install-backcapture-hook | happy
# 56-install-backcapture-hook.sh registers np-backcapture-sweep.sh as a BACKGROUNDED
# SessionStart hook (trailing ` &` so it never delays session start).
# Happy: the command lands in a temp settings.json under SessionStart, backgrounded.
# Idempotency: a second run does NOT duplicate the entry.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../56-install-backcapture-hook.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"; echo '{}' > "$CLAUDE_SETTINGS"

bash "$INSTALL" >/dev/null
bash "$INSTALL" >/dev/null   # idempotent

n="$(jq '[.hooks.SessionStart[].hooks[] | select(.command|test("np-backcapture-sweep.sh"))] | length' "$CLAUDE_SETTINGS")"
[[ "$n" == "1" ]] || { echo "FAIL: backcapture SessionStart count=$n (want 1)"; exit 1; }
jq -e '[.hooks.SessionStart[].hooks[].command] | any(test("np-backcapture-sweep.sh &$"))' "$CLAUDE_SETTINGS" >/dev/null \
  || { echo "FAIL: backcapture command not backgrounded (expected trailing &)"; exit 1; }
echo "PASS test_install_backcapture_hook"
