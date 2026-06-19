#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../53-install-playbook-hooks.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"; echo '{}' > "$CLAUDE_SETTINGS"
bash "$INSTALL" >/dev/null
bash "$INSTALL" >/dev/null   # idempotent
pre="$(jq '[.hooks.PreToolUse[].hooks[].command] | length' "$CLAUDE_SETTINGS")"
ups="$(jq '[.hooks.UserPromptSubmit[].hooks[] | select(.command|test("playbook-recall")) ] | length' "$CLAUDE_SETTINGS")"
[[ "$pre" == "2" ]] || { echo "FAIL: PreToolUse count=$pre (want 2: Bash + Read)"; exit 1; }
[[ "$ups" == "1" ]] || { echo "FAIL: playbook UserPromptSubmit count=$ups"; exit 1; }
jq -e '[.hooks.PreToolUse[].matcher] | contains(["Bash"])' "$CLAUDE_SETTINGS" >/dev/null || { echo "FAIL: Bash matcher missing"; exit 1; }
jq -e '[.hooks.PreToolUse[].matcher] | contains(["Read"])' "$CLAUDE_SETTINGS" >/dev/null || { echo "FAIL: Read matcher missing"; exit 1; }
jq -e '[.hooks.PreToolUse[].hooks[].command] | all(test("playbook-guard.sh"))' "$CLAUDE_SETTINGS" >/dev/null || { echo "FAIL: guard cmd wrong"; exit 1; }
echo "PASS test_playbook_install_hooks"
