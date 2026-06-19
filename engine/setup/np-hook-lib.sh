#!/usr/bin/env bash
# Shared helper for registering nervepack lifecycle hooks in ~/.claude/settings.json.
# SOURCE this; do not execute.
#
# np_register_hook registers BY SCRIPT BASENAME: before adding, it drops any existing
# entry in the same event whose command references the same nervepack script file. So
# re-running an installer after the script MOVED (e.g. setup/ -> engine/setup/) REPLACES
# the stale entry instead of leaving a dangling duplicate — the dedup-by-exact-command
# pattern this replaces could not migrate a path change. Re-running with an unchanged
# path is a no-op (remove-then-add the identical entry).
#
# Usage:  source "$(dirname "${BASH_SOURCE[0]}")/np-hook-lib.sh"
#         np_register_hook <event> <command> [matcher]

NP_SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

# Extract the nervepack script filename (the dedup key) from a hook command string, e.g.
#   "~/Code/nervepack/engine/setup/episodic-capture.sh session-end" -> "episodic-capture.sh"
_np_hook_basename() {
  printf '%s\n' "$1" | grep -oE '[A-Za-z0-9._-]+\.(sh|py)' | head -n1
}

np_register_hook() {  # $1=event  $2=command  $3=matcher (default "")
  local event="$1" cmd="$2" matcher="${3:-}" base tmp
  if ! command -v jq >/dev/null; then
    echo "jq is required (sudo apt install -y jq)" >&2; return 1
  fi
  mkdir -p "$(dirname "$NP_SETTINGS")"
  [ -f "$NP_SETTINGS" ] || echo '{}' > "$NP_SETTINGS"
  base="$(_np_hook_basename "$cmd")"
  tmp="$(mktemp)"
  jq --arg e "$event" --arg cmd "$cmd" --arg m "$matcher" --arg base "$base" '
    .hooks //= {} | .hooks[$e] //= [] |
    # 1) drop any existing entry in this event referencing the same script basename
    .hooks[$e] |= map(select(
      ($base == "") or (((.hooks // []) | map(.command) | join(" ")) | contains($base) | not)
    )) |
    # 2) append the fresh entry
    .hooks[$e] += [{"matcher": $m, "hooks": [{"type": "command", "command": $cmd}]}]
  ' "$NP_SETTINGS" > "$tmp" && mv "$tmp" "$NP_SETTINGS"
  echo "Registered $event hook: $cmd"
}
