#!/usr/bin/env bash
# UserPromptSubmit hook: on a session's first N prompts, inject strategies whose
# topic_triggers match the prompt, with ADVISORY framing + a relevance-gate (the
# success mirror of playbook-recall, which is imperative/enforced). Keyword-only,
# fail-open. Gated by the `strategies` toggle (`strategies.recall`).
set -uo pipefail
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled strategies.recall || exit 0; }

MAX_PROMPTS="${EPISODIC_RECALL_MAX:-2}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-layer-lib.sh" 2>/dev/null || true
# Honor an explicit single-dir override (tests); else scan the merged layer roots.
if [[ -n "${EPISODIC_STRATEGY_DIR:-}" ]]; then _st_roots=("$EPISODIC_STRATEGY_DIR"); _st_mode=override
else _st_roots=(); while IFS= read -r _r; do [[ -n "$_r" ]] && _st_roots+=("$_r/strategies"); done < <(np_merge_roots); _st_mode="$(np_merge_mode 2>/dev/null || echo override)"; fi
STATE_DIR="${EPISODIC_STATE_DIR:-/tmp/nervepack-strategy-recall}"

command -v jq >/dev/null || exit 0
_st_any=0; for _d in "${_st_roots[@]}"; do [[ -f "$_d/INDEX.md" ]] && _st_any=1; done
[[ "$_st_any" == 1 ]] || exit 0
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
for _d in "${_st_roots[@]}"; do
  INDEX="$_d/INDEX.md"; [[ -f "$INDEX" ]] || continue
  while IFS='|' read -r _ topic triggers _seencol; do
    topic="$(echo "$topic" | xargs)"
    [[ -z "$topic" || "$topic" == "topic" ]] && continue
    [[ "$topic" =~ ^-+$ ]] && continue
    slug="$(printf '%s' "$topic" | sed -E 's/^\[([^]]+)\].*/\1/')"
    [[ "$_st_mode" == override && " $_seen " == *" $slug "* ]] && continue
    hit=0
    IFS=',' read -ra kws <<< "$triggers"
    for kw in "${kws[@]}"; do
      kw="$(echo "$kw" | xargs | tr '[:upper:]' '[:lower:]')"
      [[ -n "$kw" ]] && [[ "$prompt" == *"$kw"* ]] && { hit=1; break; }
    done
    if [[ $hit == 1 ]]; then
      _seen="$_seen $slug"
      f="$_d/$slug.md"
      body="$([[ -f "$f" ]] && grep -E '^\*\*(Title|When|Do):' "$f" | tr '\n' ' ')"
      ctx+="[$slug] $body"$'\n'
    fi
  done < "$INDEX"
done
[[ -z "$ctx" ]] && exit 0

msg="Approaches that worked before (Nervepack strategies) — consider whether each applies before acting:"$'\n'"$ctx"
np_signal "$sid" "strategy-recall"
jq -nc --arg c "$msg" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
exit 0
