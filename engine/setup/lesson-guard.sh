#!/usr/bin/env bash
# PreToolUse hook: match the imminent command/tool against enforced lesson patterns.
# Phase 1: Bash command vs INDEX.md tool_match (gate=ask → confirm; gate=warn → inject).
# Phase 2: non-Bash tool_name vs armed marker + lesson frontmatter tool_name_match.
# Only enforced (provenance: failure) lessons carry a non-empty tool_match / an
# enforce: block; advisory (provenance: success) lessons are skipped (see the
# "empty tool_match = skip" filter below) -- that IS the advisory-vs-enforced split.
# Fail-open: any problem → exit 0.
set -uo pipefail
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled lessons || exit 0; [[ "$(np_param lessons.enforce on)" == "on" ]] || exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-content-lib.sh" 2>/dev/null || true
LESSON_DIR="${EPISODIC_LESSON_DIR:-$(np_layer_dir lessons)}"
INDEX="$LESSON_DIR/INDEX.md"
STATE_DIR="${EPISODIC_STATE_DIR:-/tmp/nervepack-playbook-recall}"

command -v jq >/dev/null || exit 0
[[ -f "$INDEX" ]] || exit 0

payload="$(cat)"
cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null)"
tool_name="$(printf '%s' "$payload" | jq -r '.tool_name // empty' 2>/dev/null)"
file_path="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"
sid="$(printf '%s' "$payload" | jq -r '.session_id // "unknown"' 2>/dev/null)"

fire_gate() {  # $1=gate $2=topic
  local gate="$1" topic="$2"
  local f="$LESSON_DIR/$topic.md"
  local body fp
  body="$([[ -f "$f" ]] && grep -E '^\*\*(Symptom|Why|Do|Avoid|Title|When):' "$f" | tr '\n' ' ')"
  [[ -z "$body" ]] && body="See lessons/$topic.md"
  fp="$(printf '%s' "${cmd:-${tool_name}:${file_path:-}}" | tr -s '[:space:]' ' ' | sed -E 's/^ +| +$//g' | sha256sum 2>/dev/null | cut -c1-16)"
  np_signal "$sid" "lesson-guard $gate $topic :: $fp"
  if [[ "$gate" == "ask" ]]; then
    jq -nc --arg r "Nervepack lesson '$topic': $body" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'
  else
    jq -nc --arg c "Nervepack lesson '$topic' (past failure pattern): $body" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"allow",additionalContext:$c}}'
  fi
}

# Phase 1: Bash command matching via INDEX.md tool_match patterns
if [[ -n "$cmd" ]]; then
  while IFS='|' read -r _ topic tool_match gate _rest; do
    topic="$(echo "$topic" | xargs)"; tool_match="$(echo "$tool_match" | sed -E 's/^ +| +$//g')"; gate="$(echo "$gate" | xargs)"
    [[ -z "$topic" || "$topic" == "topic" ]] && continue          # skip header
    [[ "$topic" =~ ^-+$ ]] && continue                            # skip separator
    [[ -z "$tool_match" ]] && continue                            # advisory-only lesson (no enforce)
    if printf '%s' "$cmd" | grep -qE -- "$tool_match" 2>/dev/null; then
      fire_gate "$gate" "$topic"
      exit 0
    fi
  done < "$INDEX"
fi

# Phase 2: non-Bash tool_name matching via armed marker + frontmatter tool_name_match.
# The gate fires only when playbook-recall has armed it for this session (topic match).
if [[ -n "$tool_name" && "$tool_name" != "Bash" ]]; then
  _fm_val() {  # $1=file  $2=key (2-space-indented inside enforce: block)
    awk '/^---$/{c++} c==1 && /^  '"$2"':/{v=$0; sub(/^  '"$2"':[[:space:]]*/,"",v); gsub(/"/,"",v); print v; exit} c==2{exit}' "$1" 2>/dev/null | xargs
  }
  for f in "$LESSON_DIR"/*.md; do
    [[ -f "$f" ]] || continue
    [[ "$(basename "$f")" == "INDEX.md" ]] && continue
    tnm="$(_fm_val "$f" "tool_name_match")"
    [[ -z "$tnm" ]] && continue
    [[ "$tool_name" == "$tnm" ]] || continue
    topic="$(basename "$f" .md)"
    armed="$STATE_DIR/${sid//\//_}-${topic}-gate-armed"
    [[ -f "$armed" ]] || continue
    rm -f "$armed" 2>/dev/null || true   # one-shot: disarm after firing
    gate_val="$(_fm_val "$f" "gate")"
    [[ -z "$gate_val" ]] && gate_val="warn"
    fire_gate "$gate_val" "$topic"
    exit 0
  done
fi

exit 0
