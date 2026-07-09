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

# --last-user: role-aware extraction returns the LAST GENUINE (human-typed) user
# turn. Discrimination is an allowlist on promptSource=="typed" — the field
# Claude Code stamps only on keyboard input. Many synthetic turns also arrive as
# type:"user" lines and MUST be rejected: tool_result blocks, hook
# additionalContext envelopes, <task-notification> background-task completions,
# session-continuation banners, and SDK/queued/slash-command prompts.
#
# Ordering is deliberate and matches reality: after the human's last typed
# message, assistant turns + tool_results + hook envelopes + task-notifications
# keep streaming in as later type:"user" lines. So the genuine typed message is
# NOT the last type:"user" line — synthetic ones follow it. A "return the newest
# type:user line by position" bug (or dropping the promptSource guard) therefore
# picks a synthetic turn, which is exactly the resume-pointer poisoning this
# guards against. The typed message here is plain-STRING content, which also
# closes the previously-unexercised str branch of the selection rule.
{
  jq -nc --arg t "deploy to staging" '{type:"user", promptSource:"typed", message:{role:"user",content:$t}}'
  jq -nc '{type:"assistant", message:{role:"assistant",content:[{type:"text",text:"On it."}]}}'
  # tool_result turn (type:user, no promptSource) — reject on shape AND allowlist
  jq -nc '{type:"user", message:{role:"user",content:[{tool_use_id:"toolu_1",type:"tool_result",content:"some tool output"}]}}'
  # hook additionalContext envelope (type:user, all-text, not typed) — reject
  jq -nc --arg t "<system-reminder>additionalContext injected by hook</system-reminder>" \
      '{type:"user", message:{role:"user",content:[{type:"text",text:$t}]}}'
  # session-continuation banner (plain str, NO promptSource field) — reject
  jq -nc '{type:"user", message:{role:"user",content:"This session is being continued from a previous conversation that ran out of context."}}'
  # <task-notification> background-task completion (plain str, promptSource:"system")
  # — LAST type:user line; a position/no-guard bug returns THIS. Reject.
  jq -nc '{type:"user", promptSource:"system", message:{role:"user",content:"<task-notification><task-id>abc</task-id><output>done</output></task-notification>"}}'
} > "$tmp/last_user.jsonl"

lu="$(python3 "$EX" --last-user "$tmp/last_user.jsonl")"
[[ "$lu" == "deploy to staging" ]] || { echo "FAIL: --last-user returned '$lu', want 'deploy to staging' (got a synthetic turn?)"; exit 1; }

echo "PASS test_transcript_extract"
