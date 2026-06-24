#!/usr/bin/env bash
# UserPromptSubmit hook: on a session's first N prompts, inject playbooks whose
# topic_triggers match the prompt, with IMPERATIVE framing. Keyword-only, fail-open.
set -uo pipefail
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled playbooks.recall || exit 0; }

MAX_PROMPTS="${EPISODIC_RECALL_MAX:-2}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-layer-lib.sh" 2>/dev/null || true
# Honor an explicit single-dir override (tests); else scan the merged layer roots.
if [[ -n "${EPISODIC_PLAYBOOK_DIR:-}" ]]; then _pb_roots=("$EPISODIC_PLAYBOOK_DIR")
else _pb_roots=(); while IFS= read -r _r; do [[ -n "$_r" ]] && _pb_roots+=("$_r/playbooks"); done < <(np_merge_roots); fi
_pb_mode="$(np_merge_mode 2>/dev/null || echo override)"
STATE_DIR="${EPISODIC_STATE_DIR:-/tmp/nervepack-playbook-recall}"

command -v jq >/dev/null || exit 0
_pb_any=0; for _d in "${_pb_roots[@]}"; do [[ -f "$_d/INDEX.md" ]] && _pb_any=1; done
[[ "$_pb_any" == 1 ]] || exit 0
payload="$(cat)"
sid="$(printf '%s' "$payload" | jq -r '.session_id // "unknown"' 2>/dev/null)"
prompt="$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null | tr '[:upper:]' '[:lower:]')"
[[ -n "$prompt" ]] || exit 0

mkdir -p "$STATE_DIR" || exit 0
counter="$STATE_DIR/${sid//\//_}"
count="$(cat "$counter" 2>/dev/null || echo 0)"; [[ "$count" =~ ^[0-9]+$ ]] || count=0
[[ "$count" -ge "$MAX_PROMPTS" ]] && exit 0
echo $((count+1)) > "$counter"

ctx=""; _seen=""
for _d in "${_pb_roots[@]}"; do
  INDEX="$_d/INDEX.md"; [[ -f "$INDEX" ]] || continue
  while IFS='|' read -r _ topic _tm _gate triggers _seencol; do
    topic="$(echo "$topic" | xargs)"
    [[ -z "$topic" || "$topic" == "topic" ]] && continue
    [[ "$topic" =~ ^-+$ ]] && continue
    [[ "$_pb_mode" == override && " $_seen " == *" $topic "* ]] && continue
    hit=0
    IFS=',' read -ra kws <<< "$triggers"
    for kw in "${kws[@]}"; do
      kw="$(echo "$kw" | xargs | tr '[:upper:]' '[:lower:]')"
      [[ -n "$kw" ]] && [[ "$prompt" == *"$kw"* ]] && { hit=1; break; }
    done
    if [[ $hit == 1 ]]; then
      _seen="$_seen $topic"
      f="$_d/$topic.md"
      body="$([[ -f "$f" ]] && grep -E '^\*\*(Symptom|Why|Do|Avoid):' "$f" | tr '\n' ' ')"
      ctx+="[$topic] $body"$'\n'
      if [[ -f "$f" ]] && grep -qE '^  tool_name_match:' "$f" 2>/dev/null; then
        mkdir -p "$STATE_DIR" 2>/dev/null || true
        touch "$STATE_DIR/${sid//\//_}-${topic}-gate-armed" 2>/dev/null || true
      fi
    fi
  done < "$INDEX"
done
[[ -z "$ctx" ]] && exit 0

msg="Before proceeding — past failure patterns apply (Nervepack playbooks; apply the Do/Avoid):"$'\n'"$ctx"
np_signal "$sid" "playbook-recall"
jq -nc --arg c "$msg" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
exit 0
