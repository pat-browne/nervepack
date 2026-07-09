#!/usr/bin/env bash
# SessionStart back-capture sweep: back-captures COMPLETED prior-session
# transcripts that were never captured live (Claude Code kills slow SessionEnd
# `claude -p` hooks / `/exit` doesn't fire SessionEnd), by running the existing
# capture + evaluator against the saved transcript. Idempotent, bounded, fail-open.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWEEP="$HERE/../../np-backcapture-sweep.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# --- shared env: route every cache/output path the sweep + spawned scripts use ---
export NP_TOGGLES_CONF="$tmp/toggles.conf" NP_TOGGLES_LOCAL="$tmp/local"
export CLAUDE_PROJECTS_DIR="$tmp/projects"
export BACKCAPTURE_SEEN_DIR="$tmp/bc-seen" BACKCAPTURE_QUEUE_DIR="$tmp/bc-queue" BACKCAPTURE_LOG="$tmp/bc.log"
export BACKCAPTURE_METRICS="$tmp/metrics.jsonl" BACKCAPTURE_MIN_AGE_SEC=120
export EPISODIC_INBOX="$tmp/ep-inbox" EPISODIC_SEEN_DIR="$tmp/ep-seen" EPISODIC_CAPTURE_LOG="$tmp/ep.log"
export EVAL_INBOX="$tmp/eval-inbox" EVAL_JUDGE_LOG="$tmp/eval.log" NP_SIGNAL_DIR="$tmp/sig"
printf 'memory|shared|runtime|on|\nevaluator|shared|runtime|on|\ndirective|shared|runtime|on|\n' > "$tmp/toggles.conf"

# stub claude: one object satisfying BOTH the capture note schema and the evaluator
# verdict schema (extra keys are harmless to each merge).
cat > "$tmp/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"headline":"did stuff","body":"worked on x","candidate_topics":["proj"],"keywords":["a","b"],"struggles":[],"strategies":[],"contribution_score":70,"helped":["used a skill"],"shortfalls":[],"suggestions":[],"assets_used":[]}'
STUB
chmod +x "$tmp/claude"; export CLAUDE_BIN="$tmp/claude"

mkproj() { mkdir -p "$CLAUDE_PROJECTS_DIR/proj"; }
mktranscript() {  # $1=sid  -> writes a small valid transcript with an embedded cwd
  mkproj
  local f="$CLAUDE_PROJECTS_DIR/proj/$1.jsonl"
  printf '%s\n%s\n' \
    '{"type":"user","cwd":"/home/test/proj","message":{"role":"user","content":"hi"}}' \
    '{"type":"assistant","message":{"id":"m1","role":"assistant","content":[{"type":"text","text":"hello there"}],"usage":{"input_tokens":10,"output_tokens":20,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}' \
    > "$f"
  printf '%s' "$f"
}
lines() { cat "$1"/*.jsonl 2>/dev/null | grep -c . || true; }

# portable replacement for `touch -d 'N minutes ago'` (BSD touch has no relative -d):
# GNU touch accepts @epoch; BSD touch needs -t with an epoch formatted via BSD `date -r`.
touch_ago() {  # $1=seconds-ago  $2=file
  local e=$(( $(date +%s) - $1 ))
  touch -d "@$e" "$2" 2>/dev/null || touch -t "$(date -r "$e" +%Y%m%d%H%M.%S)" "$2"
}

# --- fixtures ---
f_old="$(mktranscript 11111111-old)";    touch_ago 600 "$f_old"     # uncaptured, settled -> CAPTURE
f_active="$(mktranscript 22222222-active)"                          # just written -> SKIP (too new)
f_done="$(mktranscript 33333333-done)";  touch_ago 600 "$f_done"    # already has a metrics record -> SKIP
printf '{"session_id":"33333333-done","contribution_score":50}\n' > "$BACKCAPTURE_METRICS"
f_agent="$(mktranscript agent-44444444)"; touch_ago 600 "$f_agent"  # subagent transcript -> SKIP (not a real session)

# --- run the sweep, passing a SessionStart-style payload (current sid = the active one) ---
printf '{"session_id":"22222222-active","cwd":"/home/test/proj"}' | bash "$SWEEP"

# 1. the settled, uncaptured session was captured into BOTH inboxes (exactly once)
[[ "$(lines "$EVAL_INBOX")" == 1 ]] || { echo "FAIL: expected 1 evaluator record, got $(lines "$EVAL_INBOX")"; exit 1; }
[[ "$(lines "$EPISODIC_INBOX")" == 1 ]] || { echo "FAIL: expected 1 episodic record, got $(lines "$EPISODIC_INBOX")"; exit 1; }
cat "$EVAL_INBOX"/*.jsonl | jq -e '.session_id=="11111111-old" and .project=="proj"' >/dev/null || { echo "FAIL: evaluator record not for the old session"; exit 1; }

# 2. the active (too-new) session was skipped — not captured, not claimed
grep -q '22222222-active' "$EVAL_INBOX"/*.jsonl 2>/dev/null && { echo "FAIL: active session captured"; exit 1; }
[[ -e "$BACKCAPTURE_SEEN_DIR/22222222-active" ]] && { echo "FAIL: active session claimed (should retry once settled)"; exit 1; }

# 3. the already-in-metrics session was skipped (no dup) but marked seen
grep -q '33333333-done' "$EVAL_INBOX"/*.jsonl 2>/dev/null && { echo "FAIL: re-evaluated a session already in metrics"; exit 1; }
[[ -e "$BACKCAPTURE_SEEN_DIR/33333333-done" ]] || { echo "FAIL: in-metrics session not marked seen"; exit 1; }

# 3b. subagent transcripts (agent-*) are not real sessions — never captured
grep -q 'agent-44444444' "$EVAL_INBOX"/*.jsonl 2>/dev/null && { echo "FAIL: scored a subagent transcript"; exit 1; }

# 4. idempotent: a second sweep adds nothing
printf '{"session_id":"22222222-active","cwd":"/home/test/proj"}' | bash "$SWEEP"
[[ "$(lines "$EVAL_INBOX")" == 1 ]] || { echo "FAIL: not idempotent — evaluator records grew to $(lines "$EVAL_INBOX")"; exit 1; }
[[ "$(lines "$EPISODIC_INBOX")" == 1 ]] || { echo "FAIL: not idempotent — episodic records grew to $(lines "$EPISODIC_INBOX")"; exit 1; }

# 5. toggle off -> no work
rm -rf "$EVAL_INBOX" "$EPISODIC_INBOX" "$BACKCAPTURE_SEEN_DIR"
echo "memory.backcapture=off" > "$tmp/local"
printf '{"session_id":"x"}' | bash "$SWEEP"
[[ -d "$EVAL_INBOX" || -d "$EPISODIC_INBOX" ]] && { echo "FAIL: ran while memory.backcapture off"; exit 1; }

# 6. backlog tracking: everything eligible gets QUEUED even when MAX caps how much
# gets PROCESSED this sweep, and processing is oldest-enqueued-first (not newest-
# mtime-first, which would starve the backlog).
rm -rf "$EVAL_INBOX" "$EPISODIC_INBOX" "$BACKCAPTURE_SEEN_DIR" "$BACKCAPTURE_QUEUE_DIR" "$CLAUDE_PROJECTS_DIR"
printf 'memory.backcapture=on\nmemory.backcapture_max=1\n' > "$tmp/local"
f_older="$(mktranscript 55555555-older)"; touch_ago 1000 "$f_older"
f_newer="$(mktranscript 66666666-newer)"; touch_ago 500 "$f_newer"
printf '{"session_id":"none"}' | bash "$SWEEP"
[[ -d "$BACKCAPTURE_QUEUE_DIR" ]] || { echo "FAIL: queue dir never created"; exit 1; }
[[ -e "$BACKCAPTURE_QUEUE_DIR/55555555-older" ]] || { echo "FAIL: older session never enqueued"; exit 1; }
[[ -e "$BACKCAPTURE_QUEUE_DIR/66666666-newer" ]] || { echo "FAIL: newer session never enqueued (MAX should cap PROCESSING, not tracking)"; exit 1; }
[[ -e "$BACKCAPTURE_SEEN_DIR/55555555-older" ]] || { echo "FAIL: older session should have been processed first (oldest-enqueued-first)"; exit 1; }
[[ -e "$BACKCAPTURE_SEEN_DIR/66666666-newer" ]] && { echo "FAIL: newer session processed before older — MAX=1 should have deferred it"; exit 1; }
[[ "$(lines "$EVAL_INBOX")" == 1 ]] || { echo "FAIL: expected exactly 1 evaluator record this sweep, got $(lines "$EVAL_INBOX")"; exit 1; }
grep -q '55555555-older' "$EVAL_INBOX"/*.jsonl 2>/dev/null || { echo "FAIL: the one record processed wasn't the older session"; exit 1; }
# next sweep drains the deferred (still-queued) older-backlog item
printf '{"session_id":"none"}' | bash "$SWEEP"
[[ -e "$BACKCAPTURE_SEEN_DIR/66666666-newer" ]] || { echo "FAIL: newer session never processed on the following sweep"; exit 1; }
[[ "$(lines "$EVAL_INBOX")" == 2 ]] || { echo "FAIL: expected 2 evaluator records after draining the backlog, got $(lines "$EVAL_INBOX")"; exit 1; }

# 7. a session already tracked in the queue is still processed even after its
# transcript's mtime ages past the backcapture_days discovery window — the queue,
# not the filesystem mtime, is the source of truth for "pending" once enqueued.
rm -rf "$EVAL_INBOX" "$EPISODIC_INBOX" "$BACKCAPTURE_SEEN_DIR" "$BACKCAPTURE_QUEUE_DIR" "$CLAUDE_PROJECTS_DIR"
printf 'memory.backcapture=on\nmemory.backcapture_max=5\n' > "$tmp/local"
f_stale="$(mktranscript 77777777-stale)"; touch_ago 700000 "$f_stale"   # ~8 days old — outside the (default 7-day) window
mkdir -p "$BACKCAPTURE_QUEUE_DIR"
stale_mt=$(( $(date +%s) - 700000 ))
jq -nc --arg sid "77777777-stale" --argjson mt "$stale_mt" --arg tp "$f_stale" --arg cwd "/home/test/proj" \
  '{sid:$sid, mtime:$mt, transcript_path:$tp, cwd:$cwd}' > "$BACKCAPTURE_QUEUE_DIR/77777777-stale"
printf '{"session_id":"none"}' | bash "$SWEEP"
[[ -e "$BACKCAPTURE_SEEN_DIR/77777777-stale" ]] || { echo "FAIL: a pre-queued session outside the discovery window was silently dropped"; exit 1; }
grep -q '77777777-stale' "$EVAL_INBOX"/*.jsonl 2>/dev/null || { echo "FAIL: pre-queued stale session was never actually captured"; exit 1; }

# 8. backcapture_days is a CEILING, not a sliding re-check: a session that is
# already older than the window the FIRST time it's ever seen (no prior queue
# entry) is never enqueued and is permanently lost. This is intentional — the
# window bounds how far back discovery ever looks — but it must stay a documented,
# tested boundary, not a silent assumption. If this test ever starts failing
# because such a session DOES get captured, that's a real behavior change to a
# known data-loss edge and needs a deliberate decision, not an accidental one.
rm -rf "$EVAL_INBOX" "$EPISODIC_INBOX" "$BACKCAPTURE_SEEN_DIR" "$BACKCAPTURE_QUEUE_DIR" "$CLAUDE_PROJECTS_DIR"
printf 'memory.backcapture=on\nmemory.backcapture_max=5\n' > "$tmp/local"
f_toolold="$(mktranscript 99999999-toolold)"; touch_ago 700000 "$f_toolold"   # ~8 days old, never previously seen or queued
printf '{"session_id":"none"}' | bash "$SWEEP"
[[ -e "$BACKCAPTURE_QUEUE_DIR/99999999-toolold" ]] && { echo "FAIL: a session already outside the window on first sighting should never be enqueued"; exit 1; }
[[ -e "$BACKCAPTURE_SEEN_DIR/99999999-toolold" ]] && { echo "FAIL: a session already outside the window on first sighting should never be claimed/processed"; exit 1; }
grep -q '99999999-toolold' "$EVAL_INBOX"/*.jsonl 2>/dev/null && { echo "FAIL: a session already outside the window on first sighting should never be captured"; exit 1; }

echo "PASS test_backcapture"
