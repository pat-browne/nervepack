#!/usr/bin/env bash
# Regression test for 53-install-lesson-hooks.sh: a clean install registers the
# two lesson-guard PreToolUse entries (Bash + Read) and one lesson-recall
# UserPromptSubmit hook, idempotently; and a settings.json carrying the pre-merge
# playbook-guard/playbook-recall/strategy-recall hooks gets them migrated away.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HERE/../../53-install-lesson-hooks.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"

# --- Case 1: clean install (idempotent) ---
echo '{}' > "$CLAUDE_SETTINGS"
bash "$INSTALL" >/dev/null
bash "$INSTALL" >/dev/null   # idempotent — no duplication
pre="$(jq '[.hooks.PreToolUse[].hooks[].command] | length' "$CLAUDE_SETTINGS")"
ups="$(jq '[.hooks.UserPromptSubmit[].hooks[] | select(.command|test("lesson-recall")) ] | length' "$CLAUDE_SETTINGS")"
[[ "$pre" == "2" ]] || { echo "FAIL: PreToolUse count=$pre (want 2: Bash + Read)"; exit 1; }
[[ "$ups" == "1" ]] || { echo "FAIL: lesson-recall UserPromptSubmit count=$ups (want 1)"; exit 1; }
jq -e '[.hooks.PreToolUse[].matcher] | contains(["Bash"])' "$CLAUDE_SETTINGS" >/dev/null || { echo "FAIL: Bash matcher missing"; exit 1; }
jq -e '[.hooks.PreToolUse[].matcher] | contains(["Read"])' "$CLAUDE_SETTINGS" >/dev/null || { echo "FAIL: Read matcher missing"; exit 1; }
jq -e '[.hooks.PreToolUse[].hooks[].command] | all(test("lesson-guard.sh"))' "$CLAUDE_SETTINGS" >/dev/null || { echo "FAIL: guard cmd wrong"; exit 1; }
echo "  Case 1 OK: clean install registers 2 lesson-guard + 1 lesson-recall (idempotent)"

# --- Case 2: migration from a pre-merge settings.json ---
cat > "$CLAUDE_SETTINGS" <<'OLD'
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"~/Code/nervepack/engine/setup/playbook-guard.sh"}]}],"UserPromptSubmit":[{"hooks":[{"type":"command","command":"~/Code/nervepack/engine/setup/playbook-recall.sh"}]},{"hooks":[{"type":"command","command":"~/Code/nervepack/engine/setup/strategy-recall.sh"}]}]}}
OLD
bash "$INSTALL" >/dev/null
stale="$(jq '[.. | .command? // empty | select(test("playbook-guard|playbook-recall|strategy-recall"))] | length' "$CLAUDE_SETTINGS")"
[[ "$stale" == "0" ]] || { echo "FAIL: stale pre-merge hooks survived migration ($stale)"; exit 1; }
lg="$(jq '[.hooks.PreToolUse[].hooks[].command | select(test("lesson-guard.sh"))] | length' "$CLAUDE_SETTINGS")"
lr="$(jq '[.hooks.UserPromptSubmit[].hooks[].command | select(test("lesson-recall.sh"))] | length' "$CLAUDE_SETTINGS")"
[[ "$lg" -ge 1 && "$lr" == "1" ]] || { echo "FAIL: lesson hooks not registered after migration (lg=$lg lr=$lr)"; exit 1; }
echo "  Case 2 OK: pre-merge playbook/strategy hooks migrated to lesson hooks"

echo "PASS test_lesson_install_hooks"
