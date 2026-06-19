#!/usr/bin/env bash
# Regression: episodic-capture runs ON SessionEnd and itself calls `claude -p`.
# Headless `claude -p` ALSO fires SessionEnd (verified empirically), so without a
# guard the hook re-invokes itself forever — observed as ~1800 transcripts created
# ~1.5s apart, each nesting another "BEGIN INERT SESSION LOG" wrapper. The fix:
# every nervepack `claude -p` call exports NERVEPACK_AGENT=1, and capture exits 0
# immediately when it sees that marker. This test asserts the guard: with the
# marker set, the hook must NOT reach the summarizer (stub claude must never run)
# and must write nothing. See [[np-kb-claude-headless-scripting]] §7.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE="$HERE/../../episodic-capture.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}' > "$tmp/transcript.jsonl"

# Stub claude: if it is EVER invoked, drop a sentinel. The guard must prevent this.
cat > "$tmp/claude" <<STUB
#!/usr/bin/env bash
cat >/dev/null
touch "$tmp/claude-was-called"
printf '%s' '{"headline":"x","body":"x","candidate_topics":["x"],"keywords":["a","b","c","d","e"]}'
STUB
chmod +x "$tmp/claude"

payload="$(jq -nc --arg t "$tmp/transcript.jsonl" --arg c "$tmp/proj" '{transcript_path:$t, cwd:$c, session_id:"reentry-test"}')"

set +e
printf '%s' "$payload" \
  | NERVEPACK_AGENT=1 EPISODIC_INBOX="$tmp/inbox" CLAUDE_BIN="$tmp/claude" \
    EPISODIC_CAPTURE_LOG="$tmp/capture.log" EPISODIC_SEEN_DIR="$tmp/seen" \
    bash "$CAPTURE" session-end
rc=$?
set -e

[[ $rc -eq 0 ]]                          || { echo "FAIL: guarded hook must exit 0, got $rc"; exit 1; }
[[ ! -e "$tmp/claude-was-called" ]]      || { echo "FAIL: re-entry — capture invoked claude despite NERVEPACK_AGENT=1"; exit 1; }
[[ -z "$(cat "$tmp"/inbox/*.jsonl 2>/dev/null)" ]] || { echo "FAIL: guarded hook must not write to inbox"; exit 1; }
echo "PASS test_capture_reentry_guard"
