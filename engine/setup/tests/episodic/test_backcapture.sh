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
export BACKCAPTURE_SEEN_DIR="$tmp/bc-seen" BACKCAPTURE_LOG="$tmp/bc.log"
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

echo "PASS test_backcapture"
