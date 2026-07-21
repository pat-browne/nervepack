#!/usr/bin/env bash
# Test for 62-install-scheduled-auth-token.sh: --status is non-interactive,
# the walkthrough stores a pasted token, a second (idempotent) run does NOT
# re-prompt once fresh, --rotate forces it anyway, and empty input aborts
# without writing anything.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
INSTALLER="$SETUP/62-install-scheduled-auth-token.sh"

bash -n "$INSTALLER" || { echo "FAIL: syntax error in installer"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_CLAUDE_TOKEN_FILE="$tmp/claude-oauth-token"

# 1. --status on a fresh install reports "missing", non-interactively (no stdin needed).
out="$(NP_CLAUDE_TOKEN_FILE="$NP_CLAUDE_TOKEN_FILE" bash "$INSTALLER" --status </dev/null)"
[[ "$out" == "missing" ]] || { echo "FAIL: expected 'missing', got: $out"; exit 1; }

# 2. Piping a token through stdin runs the walkthrough and stores it.
out="$(printf 'dummy-token-value\n' | NP_CLAUDE_TOKEN_FILE="$NP_CLAUDE_TOKEN_FILE" bash "$INSTALLER")"
[[ -f "$NP_CLAUDE_TOKEN_FILE" ]] || { echo "FAIL: token file not written after walkthrough"; exit 1; }
[[ "$(cat "$NP_CLAUDE_TOKEN_FILE")" == "dummy-token-value" ]] || { echo "FAIL: stored token mismatch"; exit 1; }
[[ "$out" == *"Stored:"* ]] || { echo "FAIL: missing confirmation message: $out"; exit 1; }

# 3. Idempotent: a second default-mode run must NOT block on stdin (proves it
#    didn't re-prompt) and must report "nothing to do".
out2="$(NP_CLAUDE_TOKEN_FILE="$NP_CLAUDE_TOKEN_FILE" bash "$INSTALLER" </dev/null)"
[[ "$out2" == *"nothing to do"* ]] || { echo "FAIL: expected idempotent no-op, got: $out2"; exit 1; }

# 4. --status now reports ok.
status="$(NP_CLAUDE_TOKEN_FILE="$NP_CLAUDE_TOKEN_FILE" bash "$INSTALLER" --status </dev/null)"
[[ "$status" == ok\ * ]] || { echo "FAIL: expected 'ok <n>' after storing, got: $status"; exit 1; }

# 5. --rotate forces the walkthrough even though the token is still fresh.
out3="$(printf 'rotated-token-value\n' | NP_CLAUDE_TOKEN_FILE="$NP_CLAUDE_TOKEN_FILE" bash "$INSTALLER" --rotate)"
[[ "$(cat "$NP_CLAUDE_TOKEN_FILE")" == "rotated-token-value" ]] || { echo "FAIL: --rotate did not overwrite the token"; exit 1; }
[[ "$out3" == *"--rotate was requested"* ]] || { echo "FAIL: missing --rotate acknowledgement: $out3"; exit 1; }

# 6. Empty input aborts without writing (rotate a second time with blank paste).
before="$(cat "$NP_CLAUDE_TOKEN_FILE")"
set +e
printf '\n' | NP_CLAUDE_TOKEN_FILE="$NP_CLAUDE_TOKEN_FILE" bash "$INSTALLER" --rotate >/dev/null 2>"$tmp/stderr"
rc=$?
set -e
[[ $rc -ne 0 ]] || { echo "FAIL: empty paste should abort non-zero"; exit 1; }
[[ "$(cat "$NP_CLAUDE_TOKEN_FILE")" == "$before" ]] || { echo "FAIL: empty paste should not modify the stored token"; exit 1; }

echo "PASS test_install_scheduled_auth_token"
