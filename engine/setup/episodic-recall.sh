#!/usr/bin/env bash
# UserPromptSubmit hook: on a session's first N prompts, inject episodic themes
# matching the prompt as low-authority background context. Keyword-only (no LLM
# call), fail-open.
set -uo pipefail
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled memory.recall || exit 0; }

MAX_PROMPTS="${EPISODIC_RECALL_MAX:-2}"
TOP="${EPISODIC_RECALL_TOP:-3}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-content-lib.sh" 2>/dev/null || true
EP_DIR="${EPISODIC_DIR:-$(np_content_dir)/episodic}"
INDEX="$EP_DIR/INDEX.md"
STATE_DIR="${EPISODIC_STATE_DIR:-/tmp/nervepack-episodic-recall}"

command -v jq >/dev/null || exit 0
[[ -f "$INDEX" ]] || exit 0

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

topics="$(printf '%s' "$prompt" | "$HERE/episodic-match.sh" "$INDEX" | head -n "$TOP")"
[[ -n "$topics" ]] || exit 0

ctx="Episodic context (background — may be stale; durable skills/sources/wiki override). Consider whether each applies before acting. Matched themes from prior sessions:"
while IFS= read -r t; do
  [[ -z "$t" ]] && continue
  f="$EP_DIR/$t.md"
  [[ -f "$f" ]] && ctx+=$'\n\n'"$(sed -n '1,40p' "$f")"
done <<< "$topics"
np_signal "$sid" "episodic-recall"

jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit", additionalContext:$c}}'
exit 0
