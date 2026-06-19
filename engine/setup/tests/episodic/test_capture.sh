#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE="$HERE/../../episodic-capture.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# A fake transcript file (content irrelevant — the stub ignores it).
echo '{"role":"user","content":"hi"}' > "$tmp/transcript.jsonl"

# Stub claude: ignore all args, emit a note whose body contains a secret.
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
printf '%s' '{"headline":"did the thing","body":"worked on oauth using sk-ABCDEFGHIJKLMNOPQRSTUV today","candidate_topics":["auth-patterns"],"keywords":["oauth","login"]}'
STUB
chmod +x "$tmp/claude"

payload="$(jq -nc --arg t "$tmp/transcript.jsonl" --arg c "$tmp/proj" '{transcript_path:$t, cwd:$c}')"

printf '%s' "$payload" | EPISODIC_INBOX="$tmp/inbox" EPISODIC_SEEN_DIR="$tmp/seen" CLAUDE_BIN="$tmp/claude" bash "$CAPTURE" session-end

line="$(cat "$tmp"/inbox/*.jsonl)"
[[ -n "$line" ]] || { echo "FAIL: no inbox note written"; exit 1; }
echo "$line" | jq -e '.headline == "did the thing"' >/dev/null || { echo "FAIL: headline missing: $line"; exit 1; }
echo "$line" | jq -e '.mode == "session-end"' >/dev/null || { echo "FAIL: mode missing"; exit 1; }
echo "$line" | jq -e '.project == "proj"' >/dev/null || { echo "FAIL: project not derived: $line"; exit 1; }
echo "$line" | grep -q 'sk-ABCDEFG' && { echo "FAIL: secret leaked into inbox: $line"; exit 1; }
echo "$line" | grep -q 'REDACTED' || { echo "FAIL: secret not redacted: $line"; exit 1; }
echo "PASS test_capture"
