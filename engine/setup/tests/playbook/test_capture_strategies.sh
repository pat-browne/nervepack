#!/usr/bin/env bash
# Regression: a strategies[] array (reusable success patterns, ReasoningBank-shaped)
# survives capture + scrub into the inbox, symmetric to struggles[], with secrets
# redacted. The capture prompt now asks for strategies; this guards the pipeline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE="$HERE/../../episodic-capture.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo '{"role":"user","content":"hi"}' > "$tmp/transcript.jsonl"
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
printf '%s' '{"headline":"h","body":"b","candidate_topics":["t"],"keywords":["k"],"strategies":[{"title":"Mirror the proven pipeline","description":"when adding a memory layer","content":"reuse capture->inbox->maintain->recall; token ghp_ABCDEFGHIJKLMNOPQRSTU","topic_triggers":["memory","layer"]}]}'
STUB
chmod +x "$tmp/claude"
payload="$(jq -nc --arg t "$tmp/transcript.jsonl" --arg c "$tmp/proj" '{transcript_path:$t,cwd:$c}')"
printf '%s' "$payload" | EPISODIC_INBOX="$tmp/inbox" EPISODIC_SEEN_DIR="$tmp/seen" CLAUDE_BIN="$tmp/claude" bash "$CAPTURE" session-end
line="$(cat "$tmp"/inbox/*.jsonl)"
echo "$line" | jq -e '.strategies[0].title == "Mirror the proven pipeline"' >/dev/null || { echo "FAIL: strategies not captured: $line"; exit 1; }
echo "$line" | jq -e '(.strategies[0].topic_triggers | index("memory")) != null' >/dev/null || { echo "FAIL: topic_triggers missing"; exit 1; }
echo "$line" | grep -q 'ghp_ABCDEFG' && { echo "FAIL: secret in strategy leaked: $line"; exit 1; }
echo "$line" | grep -q 'REDACTED' || { echo "FAIL: secret not redacted"; exit 1; }
echo "PASS test_capture_strategies"
