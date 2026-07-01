#!/usr/bin/env bash
# The bash-free Windows launcher (engine/bin/nervepack-mcp.cmd) must spawn the
# server via native python with NO bash — the whole point of it. Content check
# (runs on every lane; the .cmd only executes on Windows).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CMD="$(cd "$HERE/../../.." && pwd)/bin/nervepack-mcp.cmd"

[[ -f "$CMD" ]] || { echo "FAIL: $CMD missing"; exit 1; }
grep -q 'np-mcp-server\.py' "$CMD" || { echo "FAIL: does not spawn np-mcp-server.py"; exit 1; }
grep -qi 'python' "$CMD"           || { echo "FAIL: does not use python"; exit 1; }
# The EXECUTABLE lines (not the `rem` comments, which explain it's for no-Git-bash
# hosts) must not invoke bash/sh/cygpath — the whole point is bash-freedom.
body="$(grep -viE '^[[:space:]]*(rem\b|@echo\b)' "$CMD")"
printf '%s' "$body" | grep -qiE '\b(bash|sh|cygpath)\b' && { echo "FAIL: an executable line invokes a bash tool"; exit 1; }
echo "PASS test_cmd_launcher"
