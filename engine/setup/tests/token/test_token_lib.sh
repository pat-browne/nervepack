#!/usr/bin/env bash
# Test for np-token-lib.sh: store writes a 600-perm file + issued sidecar,
# status reflects it, and the env-prefix snippet actually exports the token
# into a subshell that reads it back.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$(cd "$HERE/../.." && pwd)"
LIB="$SETUP/np-token-lib.sh"

bash -n "$LIB" || { echo "FAIL: syntax error in np-token-lib.sh"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_CLAUDE_TOKEN_FILE="$tmp/claude-oauth-token"
source "$LIB"

# 1. store() writes the file with 0600 perms and a same-day issued sidecar.
np_claude_token_store "dummy-token-value"
[[ -f "$NP_CLAUDE_TOKEN_FILE" ]] || { echo "FAIL: token file not written"; exit 1; }
perm="$(stat -f '%Lp' "$NP_CLAUDE_TOKEN_FILE" 2>/dev/null || stat -c '%a' "$NP_CLAUDE_TOKEN_FILE")"
[[ "$perm" == 600 ]] || { echo "FAIL: token file perms are $perm, expected 600"; exit 1; }
[[ -f "$NP_CLAUDE_TOKEN_FILE.issued" ]] || { echo "FAIL: issued sidecar not written"; exit 1; }
content="$(cat "$NP_CLAUDE_TOKEN_FILE")"
[[ "$content" == "dummy-token-value" ]] || { echo "FAIL: stored content mismatch: $content"; exit 1; }

# 2. status() reports a fresh ok.
status="$(np_claude_token_status)"
[[ "$status" == ok\ * ]] || { echo "FAIL: expected 'ok <n>', got: $status"; exit 1; }

# 3. env-prefix snippet, run in a clean subshell, actually exports the token.
prefix="$(np_claude_token_env_prefix)"
seen="$(env -i HOME="$HOME" PATH="$PATH" bash -c "${prefix}printf '%s' \"\$CLAUDE_CODE_OAUTH_TOKEN\"")"
[[ "$seen" == "dummy-token-value" ]] || { echo "FAIL: env-prefix did not export the token (got: $seen)"; exit 1; }

# 4. env-prefix is fail-open (no-op, no error) when the file is absent.
rm -f "$NP_CLAUDE_TOKEN_FILE" "$NP_CLAUDE_TOKEN_FILE.issued"
missing_status="$(np_claude_token_status)"
[[ "$missing_status" == "missing" ]] || { echo "FAIL: expected 'missing', got: $missing_status"; exit 1; }
prefix2="$(np_claude_token_env_prefix)"
out="$(env -i HOME="$HOME" PATH="$PATH" bash -c "${prefix2}echo ok" 2>&1)"
[[ "$out" == "ok" ]] || { echo "FAIL: env-prefix should be a silent no-op when file is absent, got: $out"; exit 1; }

echo "PASS test_token_lib"
