#!/usr/bin/env bash
# Regression: every backgrounded (`&`) lifecycle hook MUST redirect stdout+stderr.
#
# Why this matters: a `&` child inherits the hook command's stdout pipe and holds it
# open for its whole run. Claude Code reads a hook's stdout to EOF (that's how the
# SessionStart directive gets injected), so a backgrounded hook WITHOUT a redirect
# blocks session start until the child exits — the `&` does not actually detach it.
# The np-backcapture-sweep can run for minutes, so the missing redirect turned into
# multi-minute session starts. See np-kb-claude-headless-scripting.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="$HERE/../.."

# Assert the canonical unwrapped command form deterministically (np-hook-lib.sh
# otherwise auto-wraps as `bash -lc '<cmd>'` on a Git-bash kernel; the wrap itself is
# covered by tests/toggles/test_hook_lib_win_wrap.sh).
export NP_HOOK_WRAP=0

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CLAUDE_SETTINGS="$tmp/settings.json"
echo '{}' > "$CLAUDE_SETTINGS"

bash "$SETUP/50-install-session-hook.sh"   >/dev/null
bash "$SETUP/56-install-backcapture-hook.sh" >/dev/null

# All registered hook commands, across every event.
all='[.hooks | to_entries[] | .value[] | .hooks[] | .command]'

# Backgrounded commands end with `&`. Any that lack the stdout+stderr redirect are bugs.
bad="$(jq -r "$all
  | map(select(endswith(\"&\")))
  | map(select(contains(\">/dev/null 2>&1\") | not))
  | .[]" "$CLAUDE_SETTINGS")"
if [[ -n "$bad" ]]; then
  echo "FAIL: backgrounded hook(s) missing stdout/stderr redirect (will block session start):"
  printf '  %s\n' "$bad"
  exit 1
fi

# Guard against a vacuous pass: these two installers register 4 backgrounded hooks
# (SessionStart sync/dashboard/backcapture + SessionEnd sync-on-exit).
n="$(jq "$all | map(select(endswith(\"&\"))) | length" "$CLAUDE_SETTINGS")"
[[ "$n" -ge 4 ]] || { echo "FAIL: expected >=4 backgrounded hooks, got $n"; exit 1; }

echo "PASS test_background_hook_redirect"
