#!/usr/bin/env bash
# Register the lesson enforcers in ~/.claude/settings.json:
#   PreToolUse(Bash)  -> lesson-guard.sh   (gate/inject at the tool call)
#   PreToolUse(Read)  -> lesson-guard.sh   (gate/inject at the tool call)
#   UserPromptSubmit  -> lesson-recall.sh  (provenance-framed inject on topic match)
# Idempotent: re-running REPLACES stale entries — including the pre-merge
# playbook-guard/playbook-recall/strategy-recall hooks — instead of duplicating,
# so an existing install migrates cleanly to the merged lessons layer.
#
# NOTE: lesson-guard.sh appears in the same event (PreToolUse) with two
# different matchers (Bash, Read). np_register_hook deduplicates by script
# basename within an event, so it cannot register the same script twice in
# one event with different matchers without one removing the other. For that
# pair we use a direct jq remove-then-add keyed on (matcher, command) instead.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-hook-lib.sh"

# lesson-guard.sh: two PreToolUse entries with distinct matchers. Dedup key:
# (matcher, command) — drop any stale guard command (the old playbook-guard OR
# lesson-guard) in the same matcher bucket, then append lesson-guard. This
# handles path migration per-matcher without cross-contamination.
_guard_register() {  # $1=matcher  $2=command
  local m="$1" cmd="$2" tmp
  tmp="$(mktemp)"
  jq --arg m "$m" --arg cmd "$cmd" '
    .hooks //= {} | .hooks.PreToolUse //= [] |
    .hooks.PreToolUse |= map(select(
      .matcher != $m or ((.hooks // [] | map(.command) | join(" ")) | (contains("playbook-guard.sh") or contains("lesson-guard.sh")) | not)
    )) |
    .hooks.PreToolUse += [{"matcher":$m, "hooks":[{"type":"command","command":$cmd}]}]
  ' "$NP_SETTINGS" > "$tmp" && mv "$tmp" "$NP_SETTINGS"
  echo "Registered PreToolUse($m) hook: $cmd"
}

# Drop a stale UserPromptSubmit recall hook by command substring (the pre-merge
# playbook-recall / strategy-recall) before registering the merged lesson-recall.
_drop_ups() {  # $1=command-substring
  local sub="$1" tmp
  tmp="$(mktemp)"
  jq --arg sub "$sub" '
    if .hooks.UserPromptSubmit then
      .hooks.UserPromptSubmit |= map(select(
        (.hooks // [] | map(.command) | join(" ")) | contains($sub) | not))
    else . end
  ' "$NP_SETTINGS" > "$tmp" && mv "$tmp" "$NP_SETTINGS"
}

_guard_register "Bash" '~/Code/nervepack/engine/setup/lesson-guard.sh'
_guard_register "Read" '~/Code/nervepack/engine/setup/lesson-guard.sh'

_drop_ups "playbook-recall.sh"
_drop_ups "strategy-recall.sh"
np_register_hook UserPromptSubmit '~/Code/nervepack/engine/setup/lesson-recall.sh'
echo "To remove: edit $NP_SETTINGS and drop the matching entries."
