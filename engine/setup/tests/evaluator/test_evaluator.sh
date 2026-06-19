#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL="$HERE/../../np-evaluator.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local" NP_SIGNAL_DIR="$tmp/sig" EVAL_INBOX="$tmp/inbox"
printf 'evaluator|shared|runtime|on|\ndirective|shared|runtime|on|\n' > "$tmp/toggles.conf"
echo '{"type":"tool_use","name":"Bash"}' > "$tmp/t.jsonl"
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
printf '%s' '{"contribution_score":72,"helped":["used np-kb-branding"],"shortfalls":["missed a sed pitfall; token ghp_ABCDEFGHIJKLMNOPQRSTU"],"suggestions":[{"text":"add a bulk-rename playbook","confidence":0.9,"target":"playbooks","auto_safe":true}],"assets_used":[{"asset":"np-kb-branding","kind":"skill","used":true}]}'
STUB
chmod +x "$tmp/claude"
payload="$(jq -nc --arg t "$tmp/t.jsonl" --arg c "$tmp/proj" '{session_id:"s1",transcript_path:$t,cwd:$c}')"
printf '%s' "$payload" | CLAUDE_BIN="$tmp/claude" bash "$EVAL"
rec="$(cat "$tmp"/inbox/*.jsonl)"
echo "$rec" | jq -e '.contribution_score == 72' >/dev/null || { echo "FAIL: score: $rec"; exit 1; }
echo "$rec" | jq -e '.signals.tool_calls == 1' >/dev/null || { echo "FAIL: signals merged: $rec"; exit 1; }
echo "$rec" | jq -e '.session_id == "s1" and (.project=="proj")' >/dev/null || { echo "FAIL: envelope: $rec"; exit 1; }
echo "$rec" | grep -q 'ghp_ABCDEFG' && { echo "FAIL: secret leaked: $rec"; exit 1; }
echo "$rec" | grep -q 'REDACTED' || { echo "FAIL: secret not scrubbed: $rec"; exit 1; }
# cost-aware (HAL): high output tokens + low score -> a cost-flag suggestion appended.
rm -rf "$tmp/inbox"
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
printf '%s' '{"contribution_score":20,"helped":[],"shortfalls":["thrashed"],"suggestions":[],"assets_used":[]}'
STUB
chmod +x "$tmp/claude"
printf '{"type":"assistant","message":{"id":"m1","usage":{"output_tokens":300000,"input_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n' > "$tmp/big.jsonl"
payload2="$(jq -nc --arg t "$tmp/big.jsonl" --arg c "$tmp/proj" '{session_id:"s2",transcript_path:$t,cwd:$c}')"
printf '%s' "$payload2" | CLAUDE_BIN="$tmp/claude" bash "$EVAL"
rec2="$(cat "$tmp"/inbox/*.jsonl)"
echo "$rec2" | jq -e '[.suggestions[].text] | any(test("token cost"; "i"))' >/dev/null || { echo "FAIL: no cost-flag suggestion for high-cost low-score session: $rec2"; exit 1; }
# toggle off -> no record
echo "evaluator.judge=off" > "$tmp/local"; rm -rf "$tmp/inbox"
printf '%s' "$payload" | CLAUDE_BIN="$tmp/claude" bash "$EVAL"
[[ -d "$tmp/inbox" ]] && { echo "FAIL: ran while judge off"; exit 1; }
echo "PASS test_evaluator"
