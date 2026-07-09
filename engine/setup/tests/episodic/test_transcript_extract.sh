#!/usr/bin/env bash
# Unit test for np-transcript-extract.py — the shared, off-hot-path extractor that
# replaced the inline jq in episodic-capture.sh + np-evaluator.sh. Deterministic;
# no claude calls. Asserts: text/tool_use/tool_result kept, image blocks dropped,
# pathological base64 runs collapsed, and the byte cap honoured (tail = recency).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EX="$HERE/../../np-transcript-extract.py"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

blob="$(head -c 2000 < /dev/zero | tr '\0' 'A')"  # 2000-char base64-ish run
{
  jq -nc --arg t "USER_MARKER hello" '{message:{content:[{type:"text",text:$t}]}}'
  jq -nc            '{message:{content:[{type:"tool_use",name:"Bash"}]}}'
  jq -nc --arg t "TOOLRESULT_MARKER done" '{message:{content:[{type:"tool_result",content:[{type:"text",text:$t}]}]}}'
  jq -nc --arg d "$blob" '{message:{content:[{type:"image",source:{type:"base64",data:$d}}]}}'
  jq -nc --arg t "INLINE_BLOB $blob END" '{message:{content:[{type:"tool_result",content:$t}]}}'
  jq -nc --arg t "LAST_MARKER newest turn" '{message:{content:[{type:"text",text:$t}]}}'
} > "$tmp/t.jsonl"

out="$(python3 "$EX" "$tmp/t.jsonl" 0)"
grep -q 'USER_MARKER'        <<<"$out" || { echo "FAIL: text block dropped"; exit 1; }
grep -q '\[tool_use: Bash\]' <<<"$out" || { echo "FAIL: tool_use not rendered"; exit 1; }
grep -q 'TOOLRESULT_MARKER'  <<<"$out" || { echo "FAIL: tool_result text dropped"; exit 1; }
grep -q "$blob"              <<<"$out" && { echo "FAIL: image-block base64 leaked"; exit 1; }
grep -q 'binary/base64 omitted' <<<"$out" || { echo "FAIL: inline base64 run not collapsed"; exit 1; }
grep -q "$blob"              <<<"$out" && { echo "FAIL: inline base64 run leaked"; exit 1; }

# Cap keeps the TAIL (most recent), so the last marker survives a tiny cap and the
# first does not.
capped="$(python3 "$EX" "$tmp/t.jsonl" 40)"
[[ ${#capped} -le 40 ]] || { echo "FAIL: cap not honoured (${#capped} > 40)"; exit 1; }
grep -q 'LAST_MARKER' <<<"$capped" || { echo "FAIL: cap dropped the tail instead of the head"; exit 1; }

# --last-user: role-aware extraction returns the LAST genuine user text turn,
# skipping tool_result turns (arrive as type:"user" too) and hook/skill
# additionalContext envelopes (synthetic type:"user" turns marked isMeta:true
# in real transcripts) — not the newest type:"user" line by position.
{
  jq -nc --arg t "resume the migration" '{type:"user", message:{role:"user",content:[{type:"text",text:$t}]}}'
  jq -nc '{type:"assistant", message:{role:"assistant",content:[{type:"text",text:"On it."}]}}'
  jq -nc '{type:"user", message:{role:"user",content:[{tool_use_id:"toolu_1",type:"tool_result",content:"some tool output"}]}}'
  jq -nc --arg t "<system-reminder>additionalContext injected by hook</system-reminder>" \
      '{type:"user", isMeta:true, message:{role:"user",content:[{type:"text",text:$t}]}}'
} > "$tmp/last_user.jsonl"

lu="$(python3 "$EX" --last-user "$tmp/last_user.jsonl")"
[[ "$lu" == "resume the migration" ]] || { echo "FAIL: --last-user returned '$lu', want 'resume the migration'"; exit 1; }

echo "PASS test_transcript_extract"
