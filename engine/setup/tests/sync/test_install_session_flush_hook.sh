#!/usr/bin/env bash
# np-test: 55-install-session-flush-hook | happy
# 55-install-session-flush-hook.sh registers the session-flush hook (cli.py hook
# session-flush -- the bash-free port) as a SessionEnd hook (drains the local
# inboxes into the committed layers on exit).
# Happy: the command lands in a temp settings.json under SessionEnd.
# Idempotency: a second run does NOT duplicate the entry.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../55-install-session-flush-hook.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"; echo '{}' > "$CLAUDE_SETTINGS"

bash "$INSTALL" >/dev/null
bash "$INSTALL" >/dev/null   # idempotent

n="$(jq '[.hooks.SessionEnd[].hooks[] | select(.command|test("cli.py hook session-flush"))] | length' "$CLAUDE_SETTINGS")"
[[ "$n" == "1" ]] || { echo "FAIL: flush SessionEnd count=$n (want 1)"; exit 1; }
echo "PASS test_install_session_flush_hook"
