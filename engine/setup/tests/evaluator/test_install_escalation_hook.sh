#!/usr/bin/env bash
# np-test: 57-install-escalation-hook | happy
# 57-install-escalation-hook.sh registers struggle-escalation.sh as a
# UserPromptSubmit hook.
# Happy: the command lands in a temp settings.json under UserPromptSubmit.
# Idempotency: a second run does NOT duplicate the entry.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../57-install-escalation-hook.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"; echo '{}' > "$CLAUDE_SETTINGS"

bash "$INSTALL" >/dev/null
bash "$INSTALL" >/dev/null   # idempotent

n="$(jq '[.hooks.UserPromptSubmit[].hooks[] | select(.command|test("struggle-escalation.sh"))] | length' "$CLAUDE_SETTINGS")"
[[ "$n" == "1" ]] || { echo "FAIL: escalation UserPromptSubmit count=$n (want 1)"; exit 1; }
echo "PASS test_install_escalation_hook"
