#!/usr/bin/env bash
# Regression (Rule 8 — no silently-swallowed failures): when the summarizer
# returns non-JSON, capture must still fail-open (no inbox note, exit 0) BUT
# leave a discoverable breadcrumb in the capture log. The original silent
# `|| exit 0` is how the base64-garbage bug hid undetected.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE="$HERE/../../episodic-capture.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}' > "$tmp/transcript.jsonl"

# Stub claude: emit NON-JSON (simulates a failed/garbled summarization).
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' 'I could not summarize this transcript.'
STUB
chmod +x "$tmp/claude"

payload="$(jq -nc --arg t "$tmp/transcript.jsonl" --arg c "$tmp/proj" '{transcript_path:$t, cwd:$c}')"
set +e
printf '%s' "$payload" \
  | EPISODIC_INBOX="$tmp/inbox" CLAUDE_BIN="$tmp/claude" EPISODIC_CAPTURE_LOG="$tmp/capture.log" \
    bash "$CAPTURE" session-end
rc=$?
set -e

[[ $rc -eq 0 ]] || { echo "FAIL: hook must fail-open (exit 0), got $rc"; exit 1; }
[[ -z "$(cat "$tmp"/inbox/*.jsonl 2>/dev/null)" ]] || { echo "FAIL: invalid note should not be written to inbox"; exit 1; }
[[ -s "$tmp/capture.log" ]] || { echo "FAIL: no breadcrumb logged on bail"; exit 1; }
grep -qi 'json' "$tmp/capture.log" || { echo "FAIL: log should name the reason: $(cat "$tmp/capture.log")"; exit 1; }
echo "PASS test_capture_logs_bail"
