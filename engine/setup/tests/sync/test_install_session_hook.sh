#!/usr/bin/env bash
# np-test: 50-install-session-hook | happy
# 50-install-session-hook.sh registers THREE lifecycle hooks for nervepack sync +
# dashboard:
#   SessionStart: 40-sync-nervepack.sh >/dev/null 2>&1 &  (throttled background pull)
#   SessionEnd:   40-sync-nervepack.sh exit >/dev/null 2>&1 &  (primary sync on exit)
#   SessionStart: cli.py hook open-dashboard >/dev/null 2>&1 &  (refresh metrics + open dashboard)
# The `>/dev/null 2>&1` on the backgrounded commands is load-bearing — without it the
# `&` child holds the hook's stdout pipe open and blocks session start (see the
# installer's comment + tests/setup/test_background_hook_redirect.sh).
# Happy: the exact commands land in a temp settings.json under the right events.
# Idempotency: a second run does NOT duplicate (dedup is per-event by basename).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../50-install-session-hook.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"; echo '{}' > "$CLAUDE_SETTINGS"

bash "$INSTALL" >/dev/null
bash "$INSTALL" >/dev/null   # second run must not duplicate

# SessionStart holds exactly the two distinct scripts (sync + dashboard).
ss_sync="$(jq '[.hooks.SessionStart[].hooks[] | select(.command|test("40-sync-nervepack.sh >/dev/null 2>&1 &$"))] | length' "$CLAUDE_SETTINGS")"
ss_dash="$(jq '[.hooks.SessionStart[].hooks[] | select(.command|test("cli.py hook open-dashboard"))] | length' "$CLAUDE_SETTINGS")"
se_sync="$(jq '[.hooks.SessionEnd[].hooks[] | select(.command|test("40-sync-nervepack.sh exit"))] | length' "$CLAUDE_SETTINGS")"
[[ "$ss_sync" == "1" ]] || { echo "FAIL: SessionStart sync count=$ss_sync (want 1)"; exit 1; }
[[ "$ss_dash" == "1" ]] || { echo "FAIL: SessionStart dashboard count=$ss_dash (want 1)"; exit 1; }
[[ "$se_sync" == "1" ]] || { echo "FAIL: SessionEnd sync count=$se_sync (want 1)"; exit 1; }
echo "PASS test_install_session_hook"
