#!/usr/bin/env bash
# The SessionStart directive must be BYTE-STABLE across runs (no timestamps / volatile
# fields), so it forms a cache-stable prefix and the KV-cache survives between turns
# (Manus: prefix stability is the #1 cost lever). Variable, session-specific context
# is injected LATER via the UserPromptSubmit recall hooks, never interleaved here.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="$HERE/../../nervepack-session-directive.sh"
a="$(bash "$DIR" 2>/dev/null)"; b="$(bash "$DIR" 2>/dev/null)"
[[ "$a" == "$b" ]] || { echo "FAIL: directive output not byte-stable (breaks KV-cache prefix)"; diff <(printf '%s' "$a") <(printf '%s' "$b") | head; exit 1; }
[[ -n "$a" ]] || { echo "FAIL: directive produced no output"; exit 1; }
echo "PASS test_directive_stable"
