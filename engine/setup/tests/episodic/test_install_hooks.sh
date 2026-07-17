#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../52-install-episodic-hooks.sh"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"
echo '{}' > "$CLAUDE_SETTINGS"

bash "$INSTALL" >/dev/null
bash "$INSTALL" >/dev/null   # second run must not duplicate

se="$(jq '[.hooks.SessionEnd[].hooks[].command] | length' "$CLAUDE_SETTINGS")"
pc="$(jq '[.hooks.PreCompact[].hooks[].command] | length' "$CLAUDE_SETTINGS")"
up="$(jq '[.hooks.UserPromptSubmit[].hooks[].command] | length' "$CLAUDE_SETTINGS")"
[[ "$se" == "1" ]] || { echo "FAIL: SessionEnd count=$se (want 1)"; exit 1; }
[[ "$pc" == "1" ]] || { echo "FAIL: PreCompact count=$pc (want 1)"; exit 1; }
[[ "$up" == "1" ]] || { echo "FAIL: UserPromptSubmit count=$up (want 1)"; exit 1; }
jq -e '.hooks.SessionEnd[0].hooks[0].command | test("cli.py hook episodic-capture session-end")' "$CLAUDE_SETTINGS" >/dev/null \
  || { echo "FAIL: SessionEnd command wrong"; exit 1; }
jq -e '.hooks.PreCompact[0].hooks[0].command | test("cli.py hook episodic-capture checkpoint")' "$CLAUDE_SETTINGS" >/dev/null \
  || { echo "FAIL: PreCompact command wrong"; exit 1; }
echo "PASS test_install_hooks"
