#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE="$HERE/../../episodic-capture.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo '{"role":"user","content":"hi"}' > "$tmp/transcript.jsonl"
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
printf '%s' '{"headline":"h","body":"b","candidate_topics":["t"],"keywords":["k"],"struggles":[{"symptom":"blanket sed corrupted names","cause":"substring collision","fix":"guarded pass; token ghp_ABCDEFGHIJKLMNOPQRSTU","tool_match":"sed -i","topic_triggers":["rename","sed"],"destructive":false}]}'
STUB
chmod +x "$tmp/claude"
payload="$(jq -nc --arg t "$tmp/transcript.jsonl" --arg c "$tmp/proj" '{transcript_path:$t,cwd:$c}')"
printf '%s' "$payload" | EPISODIC_INBOX="$tmp/inbox" EPISODIC_SEEN_DIR="$tmp/seen" CLAUDE_BIN="$tmp/claude" bash "$CAPTURE" session-end
line="$(cat "$tmp"/inbox/*.jsonl)"
echo "$line" | jq -e '.struggles[0].symptom == "blanket sed corrupted names"' >/dev/null || { echo "FAIL: struggles not captured: $line"; exit 1; }
echo "$line" | jq -e '.struggles[0].tool_match == "sed -i"' >/dev/null || { echo "FAIL: tool_match missing"; exit 1; }
echo "$line" | grep -q 'ghp_ABCDEFG' && { echo "FAIL: secret in struggle leaked: $line"; exit 1; }
echo "$line" | grep -q 'REDACTED' || { echo "FAIL: secret not redacted"; exit 1; }
echo "PASS test_capture_struggles"
