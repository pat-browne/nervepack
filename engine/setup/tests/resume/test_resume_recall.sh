#!/usr/bin/env bash
# np-test: resume|recall
# Exercises np-resume-recall.sh (UserPromptSubmit hook): surfaces a resume offer
# when the pointer left by a PRIOR, DIFFERENT, still-fresh session exists — naming
# its branch@head(dirty), sdd ledger, and last instruction — then (always) writes
# the CURRENT session's own pointer via np-resume-write.sh --throttle. Covers the
# once-per-session surfacing guard, same-session silence, stale-pointer silence,
# and toggle-off. Hermetic: builds its own tmp git repo + toggles files, never
# touches the real $HOME/.cache/nervepack or ~/.config/nervepack.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NP="$(cd "$HERE/../../../.." && pwd)"   # tests/resume -> setup -> engine -> repo root
SCRIPT="$NP/engine/setup/np-resume-recall.sh"

fail() { echo "FAIL: $*"; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# --- a real git repo for the CURRENT session's own write to run against ---
REPO="$tmp/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q -b main
git -C "$REPO" config user.email "test@example.com"
git -C "$REPO" config user.name "Test"
echo "hello" > "$REPO/README.md"
git -C "$REPO" add README.md
git -C "$REPO" commit -q -m "baseline"

# --- a real transcript ending in a genuine typed user line ---
TRANSCRIPT="$tmp/transcript.jsonl"
cat > "$TRANSCRIPT" <<'EOF'
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"hi"}]}}
{"type":"user","promptSource":"typed","message":{"role":"user","content":"keep going on the current work"}}
EOF

seed_pointer() {  # $1=pointer-path $2=session_id $3=ts $4=branch $5=head $6=dirty $7=ledger $8=plan $9=last_instr
  jq -n \
    --argjson schema_version 1 \
    --arg session_id "$2" \
    --argjson ts "$3" \
    --arg cwd "/tmp/prior-cwd" \
    --arg git_branch "$4" \
    --arg git_head "$5" \
    --argjson git_dirty "$6" \
    --arg transcript_path "/tmp/prior-transcript.jsonl" \
    --arg last_user_instruction "$9" \
    --arg sdd_ledger "$7" \
    --arg sdd_plan "$8" \
    '{schema_version:$schema_version, session_id:$session_id, ts:$ts, cwd:$cwd,
      git_branch:$git_branch, git_head:$git_head, git_dirty:$git_dirty,
      transcript_path:$transcript_path, last_user_instruction:$last_user_instruction,
      sdd_ledger:$sdd_ledger, sdd_plan:$sdd_plan}' > "$1"
}

CURRENT_SID="current-session-456"
PRIOR_SID="prior-session-123"
PRIOR_BRANCH="feature/prior-branch"
PRIOR_HEAD="abc1234"
PRIOR_LEDGER="/tmp/prior-repo/.superpowers/sdd/progress.md"
PRIOR_PLAN="some/plan.md"
PRIOR_LAST="finish the widget refactor"

payload() {  # $1=session_id
  jq -nc --arg sid "$1" --arg cwd "$REPO" --arg tp "$TRANSCRIPT" \
    '{session_id:$sid, prompt:"resume this", cwd:$cwd, transcript_path:$tp}'
}

# ======================================================================
# CASE 1+2: fresh, different-session pointer -> offer emitted; then the
# CURRENT session's own pointer is written (session_id now == current).
# ======================================================================
export NP_TOGGLES_CONF="$tmp/toggles-empty.conf"
export NP_TOGGLES_LOCAL="$tmp/toggles-local-none"
export NP_RESUME_POINTER="$tmp/case1/pointer.json"
export NP_RESUME_STATE_DIR="$tmp/case1/state"
export NP_RESUME_STAMP="$tmp/case1/last-write"
export NP_RESUME_LOG="$tmp/case1/resume.log"
mkdir -p "$tmp/case1"

now="$(date +%s)"
seed_pointer "$NP_RESUME_POINTER" "$PRIOR_SID" "$now" "$PRIOR_BRANCH" "$PRIOR_HEAD" false "$PRIOR_LEDGER" "$PRIOR_PLAN" "$PRIOR_LAST"

out1="$(payload "$CURRENT_SID" | bash "$SCRIPT")"

ctx="$(printf '%s' "$out1" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)"
[[ -n "$ctx" ]] || fail "case1: expected an additionalContext offer, got: $out1"
printf '%s' "$ctx" | grep -qF "$PRIOR_BRANCH" || fail "case1: offer missing prior branch: $ctx"
printf '%s' "$ctx" | grep -qF "$PRIOR_LEDGER" || fail "case1: offer missing sdd_ledger path: $ctx"
printf '%s' "$ctx" | grep -qF "$PRIOR_LAST" || fail "case1: offer missing last_user_instruction: $ctx"

echo "PASS: case1 offer emitted with branch/ledger/last-instruction"

jq -e --arg v "$CURRENT_SID" '.session_id == $v' "$NP_RESUME_POINTER" >/dev/null \
  || fail "case2: pointer should now describe the CURRENT session (got $(jq -r .session_id "$NP_RESUME_POINTER" 2>/dev/null))"

echo "PASS: case2 pointer now describes current session (write happened)"

# ======================================================================
# CASE 3: once-guard — reseed a fresh different-session pointer, invoke
# again with the SAME current sid; the once-per-session marker (not the
# same-session check) must suppress the offer.
# ======================================================================
seed_pointer "$NP_RESUME_POINTER" "$PRIOR_SID" "$(date +%s)" "$PRIOR_BRANCH" "$PRIOR_HEAD" false "$PRIOR_LEDGER" "$PRIOR_PLAN" "$PRIOR_LAST"
out3="$(payload "$CURRENT_SID" | bash "$SCRIPT")"
[[ -z "$out3" ]] || fail "case3: once-guard should suppress a second offer this session, got: $out3"

echo "PASS: case3 once-guard suppresses repeat offer"

# ======================================================================
# CASE 4: pointer.session_id == current session -> silent (no offer).
# ======================================================================
export NP_RESUME_POINTER="$tmp/case4/pointer.json"
export NP_RESUME_STATE_DIR="$tmp/case4/state"
export NP_RESUME_STAMP="$tmp/case4/last-write"
export NP_RESUME_LOG="$tmp/case4/resume.log"
mkdir -p "$tmp/case4"
SAME_SID="same-session-789"
seed_pointer "$NP_RESUME_POINTER" "$SAME_SID" "$(date +%s)" "$PRIOR_BRANCH" "$PRIOR_HEAD" false "$PRIOR_LEDGER" "$PRIOR_PLAN" "$PRIOR_LAST"
out4="$(payload "$SAME_SID" | bash "$SCRIPT")"
[[ -z "$out4" ]] || fail "case4: same-session pointer should stay silent, got: $out4"

echo "PASS: case4 same-session -> silent"

# ======================================================================
# CASE 5: stale pointer (ts far in the past) -> silent (no offer).
# Non-vacuity: temporarily disable the freshness check and confirm the
# stale pointer WRONGLY produces an offer (the test below catches it),
# then restore and re-verify silence.
# ======================================================================
export NP_RESUME_POINTER="$tmp/case5/pointer.json"
export NP_RESUME_STATE_DIR="$tmp/case5/state"
export NP_RESUME_STAMP="$tmp/case5/last-write"
export NP_RESUME_LOG="$tmp/case5/resume.log"
mkdir -p "$tmp/case5"
STALE_TS=$(( $(date +%s) - 999999 ))
seed_pointer "$NP_RESUME_POINTER" "$PRIOR_SID" "$STALE_TS" "$PRIOR_BRANCH" "$PRIOR_HEAD" false "$PRIOR_LEDGER" "$PRIOR_PLAN" "$PRIOR_LAST"

# --- non-vacuity demo: break the freshness check, confirm the test would fail ---
BROKEN="$tmp/np-resume-recall.broken.sh"
sed -E 's/\[\[ "\$age" -ge 0 \&\& "\$age" -lt "\$max_age" \]\]/[[ 1 == 1 ]]/' "$SCRIPT" > "$BROKEN"
chmod +x "$BROKEN"
mkdir -p "$tmp/case5/state-broken"
broken_out="$(payload "distinct-current-sid" | NP_RESUME_STATE_DIR="$tmp/case5/state-broken" bash "$BROKEN")"
[[ -n "$broken_out" ]] || fail "non-vacuity: broken freshness-check script unexpectedly stayed silent on a stale pointer — case5 would be vacuous"
echo "PASS: non-vacuity demo — disabling the freshness check does make the stale pointer offer (case5 is non-vacuous)"

# --- real check: with the freshness guard intact, stale -> silent ---
rm -rf "$tmp/case5/state"; mkdir -p "$tmp/case5/state"
out5="$(payload "distinct-current-sid" | bash "$SCRIPT")"
[[ -z "$out5" ]] || fail "case5: stale pointer should stay silent, got: $out5"

echo "PASS: case5 stale pointer -> silent"

# ======================================================================
# CASE 6: toggle off -> silent, and no write either.
# ======================================================================
export NP_RESUME_POINTER="$tmp/case6/pointer.json"
export NP_RESUME_STATE_DIR="$tmp/case6/state"
export NP_RESUME_STAMP="$tmp/case6/last-write"
export NP_RESUME_LOG="$tmp/case6/resume.log"
mkdir -p "$tmp/case6"
seed_pointer "$NP_RESUME_POINTER" "$PRIOR_SID" "$(date +%s)" "$PRIOR_BRANCH" "$PRIOR_HEAD" false "$PRIOR_LEDGER" "$PRIOR_PLAN" "$PRIOR_LAST"
before_hash="$(shasum "$NP_RESUME_POINTER" | awk '{print $1}')"

export NP_TOGGLES_CONF="$tmp/toggles-off.conf"
printf 'resume|shared|runtime|off|\n' > "$NP_TOGGLES_CONF"

out6="$(payload "toggle-off-sid" | bash "$SCRIPT")"
[[ -z "$out6" ]] || fail "case6: toggle off should stay silent, got: $out6"

after_hash="$(shasum "$NP_RESUME_POINTER" | awk '{print $1}')"
[[ "$before_hash" == "$after_hash" ]] || fail "case6: toggle off should not write the pointer either"

export NP_TOGGLES_CONF="$tmp/toggles-empty.conf"

echo "PASS: case6 toggle off -> silent, no write"

echo "PASS test_resume_recall"
