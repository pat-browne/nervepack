#!/usr/bin/env bash
# UserPromptSubmit hook: after MIN_PROMPTS have passed, if playbook-guard fires
# >= MIN_STRUGGLES in this session, inject a one-time reminder to check skill-
# applicability or np-core-suggestions-review. Fires at most once per session.
# Fail-open: any error → exit 0 silently.
set -uo pipefail
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"
[[ -r "$_npl" ]] && source "$_npl" && { np_enabled evaluator.escalation || exit 0; }

MIN_STRUGGLES="${NP_ESCALATION_MIN_STRUGGLES:-2}"
MIN_PROMPTS="${NP_ESCALATION_MIN_PROMPTS:-3}"
STATE_DIR="${NP_ESCALATION_STATE:-/tmp/nervepack-escalation}"

command -v jq >/dev/null || exit 0

payload="$(cat)"
sid="$(printf '%s' "$payload" | jq -r '.session_id // "unknown"' 2>/dev/null)"
[[ -n "$sid" && "$sid" != "unknown" ]] || exit 0

mkdir -p "$STATE_DIR" || exit 0

# Idempotency: fire at most once per session
fired="$STATE_DIR/fired_${sid//\//_}"
[[ -f "$fired" ]] && exit 0

# Count prompts this session; escalate only after MIN_PROMPTS have passed
pcnt_file="$STATE_DIR/cnt_${sid//\//_}"
pcount="$(cat "$pcnt_file" 2>/dev/null || echo 0)"
[[ "$pcount" =~ ^[0-9]+$ ]] || pcount=0
echo $((pcount + 1)) > "$pcnt_file"
[[ "$pcount" -ge "$MIN_PROMPTS" ]] || exit 0

# Count playbook-guard fires in this session's signal log (struggle proxy:
# each fire = a Bash tool call that matched a known failure pattern)
log_file="${NP_SIGNAL_DIR:-$HOME/.cache/nervepack/session-signals}/${sid//\//_}.log"
pg_count=0
if [[ -f "$log_file" ]]; then
    pg_count=$(grep -c '^playbook-guard' "$log_file" 2>/dev/null || echo 0)
fi
[[ "$pg_count" =~ ^[0-9]+$ ]] || pg_count=0
[[ "$pg_count" -ge "$MIN_STRUGGLES" ]] || exit 0

# Condition met: mark as fired and inject reminder
touch "$fired"
np_signal "$sid" "struggle-escalation"

msg="Mid-session escalation (Nervepack): ${pg_count} repeated pattern-trigger events detected in this session. Consider invoking np-core-suggestions-review to act on past evaluator suggestions, or check whether a skill applies before continuing."
jq -nc --arg c "$msg" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
exit 0
