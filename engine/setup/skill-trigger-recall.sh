#!/usr/bin/env bash
# UserPromptSubmit hook: inject a once-per-session reminder to invoke
# superpowers:writing-skills when the prompt matches a skill-writing pattern
# (skill.*refactor, refactor.*skill, or SKILL.md reference). Fail-open.
set -uo pipefail
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"
[[ -r "$_npl" ]] && source "$_npl" && { np_enabled skills.trigger_recall || exit 0; }

STATE_DIR="${NP_SKILL_TRIGGER_STATE:-/tmp/nervepack-skill-trigger}"
PATTERNS="skill.*refactor|refactor.*skill|skill\.md"

command -v jq >/dev/null || exit 0

payload="$(cat)"
sid="$(printf '%s' "$payload" | jq -r '.session_id // "unknown"' 2>/dev/null)"
[[ -n "$sid" && "$sid" != "unknown" ]] || exit 0
prompt="$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null | tr '[:upper:]' '[:lower:]')"
[[ -n "$prompt" ]] || exit 0

mkdir -p "$STATE_DIR" || exit 0
fired="$STATE_DIR/fired_${sid//\//_}"
[[ -f "$fired" ]] && exit 0

[[ "$prompt" =~ $PATTERNS ]] || exit 0

touch "$fired"
np_signal "$sid" "skill-trigger-recall"

msg="Skill-writing trigger (Nervepack): this prompt matches a skill-writing pattern. Invoke the superpowers:writing-skills skill BEFORE proceeding."
jq -nc --arg c "$msg" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
exit 0
