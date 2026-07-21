#!/usr/bin/env bash
# Provisions the long-lived claude OAuth token that scheduled nervepack jobs
# (launchd/cron/schtasks) need — see np-token-lib.sh for why. This is
# nervepack's one genuinely-manual onboarding step: `claude setup-token`
# requires a real interactive terminal + a browser approval, so it cannot be
# scripted end-to-end. Everything else (storage, permissions, wiring into
# every scheduled job, rotation tracking) is automated.
#
# Usage:
#   62-install-scheduled-auth-token.sh            idempotent — walkthrough only
#                                                  runs if missing or in the
#                                                  rotation window
#   62-install-scheduled-auth-token.sh --status    non-interactive status line
#                                                  (used by np-doctor.sh)
#   62-install-scheduled-auth-token.sh --rotate    force the walkthrough even
#                                                  if the current token is
#                                                  still fresh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-token-lib.sh"

mode="${1:-}"

if [[ "$mode" == "--status" ]]; then
  np_claude_token_status
  exit 0
fi

status_line="$(np_claude_token_status)"
status_word="${status_line%% *}"

if [[ "$mode" != "--rotate" && "$status_word" == ok ]]; then
  echo "scheduled-auth-token: $status_line — nothing to do."
  exit 0
fi

case "$status_word" in
  missing) echo "No scheduled-auth token configured yet." ;;
  warn)    echo "Token is inside its rotation window ($status_line) — time to refresh it." ;;
  ok)      echo "Token is still fresh ($status_line) but --rotate was requested." ;;
esac

cat <<'EOM'

This is the one manual step (a browser approval — it can't be scripted):

  1. In a REAL terminal (not piped through an agent/automation tool), run:
       claude setup-token
  2. Approve access in the browser window that opens.
  3. Copy the printed token (the line after "Your OAuth token (valid for 1 year):").

Paste it below. Input is hidden and written straight to a 600-permission
file — it is never echoed back or logged anywhere.
EOM

read -rsp "Paste token: " token
echo
if [[ -z "$token" ]]; then
  echo "No token entered — aborting, nothing written." >&2
  exit 1
fi

np_claude_token_store "$token"
unset token

echo "Stored: $(np_claude_token_file)"
echo "Every scheduled nervepack job re-reads this file at run time — no reload or"
echo "reinstall of the launchd/cron/schtasks jobs is needed, now or on future rotations."
echo "Check status any time with: $0 --status"
