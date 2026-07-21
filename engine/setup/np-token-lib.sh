#!/usr/bin/env bash
# Shared helper: provisions/reads a long-lived claude OAuth token
# (`claude setup-token`) so SCHEDULED nervepack jobs (launchd/cron/schtasks)
# can authenticate. Scheduler-spawned processes don't inherit the interactive
# session's OAuth/keychain auth, so the agentic crons (memory-promote, refine,
# compact) fail "Not logged in" without this (nervepack lesson
# [nervepack-scheduled-auth]).
#
# Sourced by: 62-install-scheduled-auth-token.sh, the 70-install-memory-*.sh
# family (all three scheduler backends), and np-doctor.sh's
# scheduled-auth-token check.
#
# Design: the token lives in ONE file. Every scheduled job's generated command
# re-reads that file at RUN TIME (np_claude_token_env_prefix, below) rather
# than having the token baked into the plist/crontab/task at install time —
# so rotating the token later is just overwriting the file; no
# reinstall/reload of any scheduled job is needed.
NP_CLAUDE_TOKEN_FILE="${NP_CLAUDE_TOKEN_FILE:-$HOME/.config/nervepack/claude-oauth-token}"
NP_TOKEN_STATUS_PY="${NP_TOKEN_STATUS_PY:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np_token_status.py}"

np_claude_token_file() { printf '%s\n' "$NP_CLAUDE_TOKEN_FILE"; }

# Emits a shell snippet to PREPEND to a scheduled job's command. Fail-open: if
# the file isn't there yet (or unreadable), this is a silent no-op and the job
# runs exactly as it did before this feature existed.
np_claude_token_env_prefix() {
  printf 'f=%q; [ -r "$f" ] && export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$f")"; ' "$NP_CLAUDE_TOKEN_FILE"
}

# Writes $1 to the token file (0600) plus an issued-date sidecar used for
# rotation tracking (np_token_status.py). umask first so the file is never
# briefly world-readable between create and chmod.
np_claude_token_store() {
  local token="$1"
  mkdir -p "$(dirname "$NP_CLAUDE_TOKEN_FILE")"
  ( umask 077; printf '%s' "$token" > "$NP_CLAUDE_TOKEN_FILE" )
  chmod 600 "$NP_CLAUDE_TOKEN_FILE"
  date -u +%Y-%m-%d > "$NP_CLAUDE_TOKEN_FILE.issued"
  chmod 600 "$NP_CLAUDE_TOKEN_FILE.issued"
}

# "missing" | "ok <days_left>" | "warn <days_left>" — see np_token_status.py.
np_claude_token_status() {
  python3 "$NP_TOKEN_STATUS_PY" "$NP_CLAUDE_TOKEN_FILE"
}
