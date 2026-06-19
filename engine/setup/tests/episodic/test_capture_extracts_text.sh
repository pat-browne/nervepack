#!/usr/bin/env bash
# Regression: episodic-capture must feed the summarizer the READABLE conversation
# text, not a raw byte-tail of the JSONL. Real transcripts embed large base64
# image/attachment blobs; a byte-tail (`tail -c`) lands inside one and hands the
# summarizer 200KB of base64 garbage, so it emits no valid JSON and capture
# silently bails — which is why episodic memory came up empty.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE="$HERE/../../episodic-capture.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# 300KB of base64-ish filler ending in a recognizable sentinel, so a byte-tail
# would land squarely inside the attachment blob. (Via file + --rawfile: 300KB
# on a jq command line blows ARG_MAX.)
{ head -c 300000 < /dev/zero | tr '\0' 'A'; printf 'GARBAGE_SENTINEL'; } > "$tmp/big.txt"

{
  jq -nc --arg t "CONVO_USER_MARKER asked about the dashboard launch loop" \
    '{type:"user",message:{role:"user",content:[{type:"text",text:$t}]}}'
  jq -nc --arg t "CONVO_ASSISTANT_MARKER fixed it once-per-boot" \
    '{type:"assistant",message:{role:"assistant",content:[{type:"text",text:$t}]}}'
  jq -nc --rawfile d "$tmp/big.txt" \
    '{type:"user",message:{role:"user",content:[{type:"image",source:{type:"base64",media_type:"image/png",data:$d}}]}}'
} > "$tmp/transcript.jsonl"

# Stub claude: capture exactly what it receives on stdin, then emit a valid note.
cat > "$tmp/claude" <<STUB
#!/usr/bin/env bash
cat > "$tmp/fed_prompt.txt"
printf '%s' '{"headline":"x","body":"y","candidate_topics":["t"],"keywords":["k"]}'
STUB
chmod +x "$tmp/claude"

payload="$(jq -nc --arg t "$tmp/transcript.jsonl" --arg c "$tmp/proj" '{transcript_path:$t, cwd:$c}')"
printf '%s' "$payload" | EPISODIC_INBOX="$tmp/inbox" EPISODIC_SEEN_DIR="$tmp/seen" CLAUDE_BIN="$tmp/claude" bash "$CAPTURE" session-end

fed="$(cat "$tmp/fed_prompt.txt" 2>/dev/null || true)"
grep -q 'CONVO_USER_MARKER'      <<<"$fed" || { echo "FAIL: user text not fed to summarizer"; exit 1; }
grep -q 'CONVO_ASSISTANT_MARKER' <<<"$fed" || { echo "FAIL: assistant text not fed to summarizer"; exit 1; }
grep -q 'GARBAGE_SENTINEL'       <<<"$fed" && { echo "FAIL: base64 attachment garbage fed to summarizer"; exit 1; }

# The output instruction must come AFTER the transcript (recency), and a guard
# must tell the model not to continue the conversation — otherwise, fed a real
# transcript ending in a question, it answers AS the assistant instead of
# summarizing (observed with haiku on a 180KB transcript).
upos="$(grep -abo 'CONVO_ASSISTANT_MARKER' <<<"$fed" | head -1 | cut -d: -f1)"
ipos="$(grep -abo 'STRICT JSON' <<<"$fed" | head -1 | cut -d: -f1)"
[[ -n "$upos" && -n "$ipos" && "$ipos" -gt "$upos" ]] || { echo "FAIL: output instruction must follow the transcript (got transcript@$upos instruction@$ipos)"; exit 1; }
grep -qi 'do not continue' <<<"$fed" || { echo "FAIL: missing 'do not continue the conversation' guard"; exit 1; }
echo "PASS test_capture_extracts_text"
