#!/usr/bin/env bash
# UserPromptSubmit hook: on a session's first N prompts, inject lessons whose
# topic_triggers match the prompt (memory/lessons/, via np_layer_dir/np_layer_roots).
# Merge of playbook-recall.sh + strategy-recall.sh: framing now branches on the
# matched entry's `provenance` frontmatter instead of living in two hooks --
#   provenance: failure -> imperative "past failure pattern" wording (was playbook-recall)
#   provenance: success -> advisory  "approach that worked"  wording (was strategy-recall)
# A topic .md file may carry BOTH provenances back to back (a topic that was in
# both playbooks and strategies pre-merge) -- each block is surfaced with its own
# framing. Keyword-only, fail-open. Gated by the `lessons` toggle.
set -uo pipefail
_npl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/np-toggle-lib.sh"; [[ -r "$_npl" ]] && source "$_npl" && { np_enabled lessons || exit 0; }

MAX_PROMPTS="${EPISODIC_RECALL_MAX:-2}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/np-layer-lib.sh" 2>/dev/null || true
# Honor an explicit single-dir override (tests); else scan the merged layer roots.
if [[ -n "${EPISODIC_LESSON_DIR:-}" ]]; then _ls_roots=("$EPISODIC_LESSON_DIR"); _ls_mode=override
else _ls_roots=(); while IFS= read -r _r; do [[ -n "$_r" ]] && _ls_roots+=("$_r"); done < <(np_layer_roots lessons); _ls_mode="$(np_merge_mode 2>/dev/null || echo override)"; fi
# Shared with lesson-guard.sh's default (carried over from playbook-recall.sh/
# playbook-guard.sh pre-merge) so the tool_name_match armed-marker handoff below
# keeps working without an explicit EPISODIC_STATE_DIR override.
STATE_DIR="${EPISODIC_STATE_DIR:-/tmp/nervepack-playbook-recall}"

command -v jq >/dev/null || exit 0
_ls_any=0; for _d in ${_ls_roots[@]+"${_ls_roots[@]}"}; do [[ -f "$_d/INDEX.md" ]] && _ls_any=1; done
[[ "$_ls_any" == 1 ]] || exit 0
payload="$(cat)"
sid="$(printf '%s' "$payload" | jq -r '.session_id // "unknown"' 2>/dev/null)"
prompt="$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null | tr '[:upper:]' '[:lower:]')"
[[ -n "$prompt" ]] || exit 0

mkdir -p "$STATE_DIR" || exit 0
counter="$STATE_DIR/${sid//\//_}"
count="$(cat "$counter" 2>/dev/null || echo 0)"; [[ "$count" =~ ^[0-9]+$ ]] || count=0
[[ "$count" -ge "$MAX_PROMPTS" ]] && exit 0
echo $((count+1)) > "$counter"

# _ls_blocks <file> -> one line per frontmatter+body block: "<provenance>\x1f<body>".
# A lesson file is 1 block (single-provenance) or 2 (merged playbook+strategy
# entry back to back); every `^---$` line toggles frontmatter/body, same
# assumption np-migrate-lessons.py / lesson-guard.sh's _fm_val already make
# (body text never contains a standalone `---` line).
_ls_blocks() {
  awk '
    /^---$/ { c++; next }
    {
      blk = int((c + 1) / 2)
      if (blk < 1) next
      if (c % 2 == 1) {
        if ($0 ~ /^provenance:[ \t]*/) { sub(/^provenance:[ \t]*/, ""); prov[blk] = $0 }
      } else {
        if ($0 ~ /^\*\*(Symptom|Why|Do|Avoid|Title|When):/) { body[blk] = body[blk] $0 " " }
      }
    }
    END { for (b = 1; (b in prov); b++) printf "%s\x1f%s\n", prov[b], body[b] }
  ' "$1" 2>/dev/null
}

fail_ctx=""; success_ctx=""; _seen=""
for _d in ${_ls_roots[@]+"${_ls_roots[@]}"}; do
  INDEX="$_d/INDEX.md"; [[ -f "$INDEX" ]] || continue
  while IFS='|' read -r _ topic _tm _gate triggers _rest; do
    topic="$(echo "$topic" | xargs)"
    [[ -z "$topic" || "$topic" == "topic" ]] && continue
    [[ "$topic" =~ ^-+$ ]] && continue
    [[ "$_ls_mode" == override && " $_seen " == *" $topic "* ]] && continue
    hit=0
    IFS=',' read -ra kws <<< "$triggers"
    for kw in "${kws[@]}"; do
      kw="$(echo "$kw" | xargs | tr '[:upper:]' '[:lower:]')"
      [[ -n "$kw" ]] && [[ "$prompt" == *"$kw"* ]] && { hit=1; break; }
    done
    if [[ $hit == 1 ]]; then
      _seen="$_seen $topic"
      f="$_d/$topic.md"
      if [[ -f "$f" ]]; then
        while IFS=$'\x1f' read -r prov body; do
          case "$prov" in
            failure)
              fail_ctx+="[$topic] $body"$'\n'
              if grep -qE '^  tool_name_match:' "$f" 2>/dev/null; then
                mkdir -p "$STATE_DIR" 2>/dev/null || true
                touch "$STATE_DIR/${sid//\//_}-${topic}-gate-armed" 2>/dev/null || true
              fi
              ;;
            success)
              success_ctx+="[$topic] $body"$'\n'
              ;;
          esac
        done < <(_ls_blocks "$f")
      fi
    fi
  done < "$INDEX"
done

ctx=""
[[ -n "$fail_ctx" ]] && ctx+="Before proceeding — past failure patterns apply (Nervepack lessons; apply the Do/Avoid):"$'\n'"$fail_ctx"
[[ -n "$success_ctx" ]] && ctx+="Approaches that worked before (Nervepack lessons) — consider whether each applies before acting:"$'\n'"$success_ctx"
[[ -z "$ctx" ]] && exit 0

np_signal "$sid" "lesson-recall"
jq -nc --arg c "$ctx" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$c}}'
exit 0
