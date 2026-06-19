#!/usr/bin/env bash
# Register the playbook enforcers in ~/.claude/settings.json:
#   PreToolUse(Bash)  -> playbook-guard.sh  (gate/inject at the tool call)
#   PreToolUse(Read)  -> playbook-guard.sh  (gate/inject at the tool call)
#   UserPromptSubmit  -> playbook-recall.sh (imperative inject on topic match)
#   UserPromptSubmit  -> strategy-recall.sh (advisory injection of reusable strategies)
# Idempotent: re-running after a script path change REPLACES the stale entry
# instead of duplicating it (handled by np-hook-lib.sh register-by-basename).
#
# NOTE: playbook-guard.sh appears in the same event (PreToolUse) with two
# different matchers (Bash, Read). np_register_hook deduplicates by script
# basename within an event, so it cannot register the same script twice in
# one event with different matchers without one removing the other. For that
# pair we use a direct jq remove-then-add keyed on (matcher, command) instead.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

# playbook-guard.sh: two PreToolUse entries with distinct matchers.
# Dedup key: (matcher, command) — drop stale command in the same matcher bucket,
# then append. This handles path migration per-matcher without cross-contamination.
_guard_register() {  # $1=matcher  $2=command
  local m="$1" cmd="$2" tmp
  tmp="$(mktemp)"
  jq --arg m "$m" --arg cmd "$cmd" '
    .hooks //= {} | .hooks.PreToolUse //= [] |
    .hooks.PreToolUse |= map(select(
      .matcher != $m or ((.hooks // [] | map(.command) | join(" ")) | contains("playbook-guard.sh") | not)
    )) |
    .hooks.PreToolUse += [{"matcher":$m, "hooks":[{"type":"command","command":$cmd}]}]
  ' "$NP_SETTINGS" > "$tmp" && mv "$tmp" "$NP_SETTINGS"
  echo "Registered PreToolUse($m) hook: $cmd"
}

_guard_register "Bash" '~/Code/nervepack/engine/setup/playbook-guard.sh'
_guard_register "Read" '~/Code/nervepack/engine/setup/playbook-guard.sh'

np_register_hook UserPromptSubmit '~/Code/nervepack/engine/setup/playbook-recall.sh'
# Success mirror of playbook-recall: advisory injection of reusable strategies.
np_register_hook UserPromptSubmit '~/Code/nervepack/engine/setup/strategy-recall.sh'
echo "To remove: edit $NP_SETTINGS and drop the matching entries."
