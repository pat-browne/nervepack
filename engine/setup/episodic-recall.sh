#!/usr/bin/env bash
# UserPromptSubmit hook: on a session's first N prompts, inject episodic themes
# matching the prompt as low-authority background context. Keyword-only (no LLM
# call), fail-open.
set -uo pipefail
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled memory.recall || exit 0; }

MAX_PROMPTS="${EPISODIC_RECALL_MAX:-2}"
TOP="${EPISODIC_RECALL_TOP:-3}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-layer-lib.sh" 2>/dev/null || true
if [[ -n "${EPISODIC_DIR:-}" ]]; then _ep_roots=("$EPISODIC_DIR"); _ep_mode=override
else _ep_roots=(); while IFS= read -r _r; do [[ -n "$_r" ]] && _ep_roots+=("$_r/episodic"); done < <(np_merge_roots); _ep_mode="$(np_merge_mode 2>/dev/null || echo override)"; fi
STATE_DIR="${EPISODIC_STATE_DIR:-/tmp/nervepack-episodic-recall}"

command -v jq >/dev/null || exit 0
_ep_any=0; for _d in "${_ep_roots[@]}"; do [[ -f "$_d/INDEX.md" ]] && _ep_any=1; done
[[ "$_ep_any" == 1 ]] || exit 0

payload="$(cat)"
sid="$(printf '%s' "$payload" | jq -r '.session_id // "unknown"' 2>/dev/null)"
prompt="$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null)"
[[ -n "$prompt" ]] || exit 0

mkdir -p "$STATE_DIR" || exit 0
counter="$STATE_DIR/${sid//\//_}"
count="$(cat "$counter" 2>/dev/null || echo 0)"
[[ "$count" =~ ^[0-9]+$ ]] || count=0
[[ "$count" -ge "$MAX_PROMPTS" ]] && exit 0
echo $((count + 1)) > "$counter"

ctx="Episodic context (background — may be stale; durable skills/sources/wiki override). Consider whether each applies before acting. Matched themes from prior sessions:"
_emitted=""; _hit_any=0
for _d in "${_ep_roots[@]}"; do
  INDEX="$_d/INDEX.md"; [[ -f "$INDEX" ]] || continue
  while IFS= read -r t; do
    [[ -z "$t" ]] && continue
    [[ "$_ep_mode" == override && " $_emitted " == *" $t "* ]] && continue
    f="$_d/$t.md"; [[ -f "$f" ]] || continue
    _emitted="$_emitted $t"; _hit_any=1
    ctx+=$'\n\n'"$(sed -n '1,40p' "$f")"
  done < <(printf '%s' "$prompt" | "$HERE/episodic-match.sh" "$INDEX" | head -n "$TOP")
done
[[ "$_hit_any" == 1 ]] || exit 0
np_signal "$sid" "episodic-recall"

jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit", additionalContext:$c}}'
exit 0
