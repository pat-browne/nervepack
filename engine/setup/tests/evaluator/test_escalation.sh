#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$HERE/../../struggle-escalation.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/signals" "$tmp/state"

run() {
    printf '%s' "$1" | \
        NP_ESCALATION_STATE="$tmp/state" \
        NP_SIGNAL_DIR="$tmp/signals" \
        NP_ESCALATION_MIN_STRUGGLES=2 \
        NP_ESCALATION_MIN_PROMPTS=3 \
        bash "$HOOK"
}

payload() { jq -nc --arg sid "$1" '{session_id:$sid,prompt:"test"}'; }

# --- session s1: 2 guard fires, should escalate on 4th prompt ---
printf 'playbook-guard warn bash-nested-substitution :: abc123\n' >> "$tmp/signals/s1.log"
printf 'playbook-guard warn bash-nested-substitution :: def456\n' >> "$tmp/signals/s1.log"

# First 3 prompts: too early, no escalation
for i in 1 2 3; do
    out="$(run "$(payload s1)")"
    [[ -z "$out" ]] || { echo "FAIL: premature escalation on prompt $i: $out"; exit 1; }
done

# 4th prompt: pcount=3 >= MIN_PROMPTS=3, guard_fires=2 >= 2 → should fire
out="$(run "$(payload s1)")"
[[ -n "$out" ]] || { echo "FAIL: expected escalation on prompt 4, got nothing"; exit 1; }
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | test("escalation")' >/dev/null \
    || { echo "FAIL: output missing 'escalation' keyword: $out"; exit 1; }
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | test("np-core-suggestions-review")' >/dev/null \
    || { echo "FAIL: output missing skill name: $out"; exit 1; }

# 5th prompt: idempotency marker present → silent
out="$(run "$(payload s1)")"
[[ -z "$out" ]] || { echo "FAIL: escalated twice for session s1: $out"; exit 1; }

# --- session s2: only 1 guard fire → never escalates ---
printf 'playbook-guard warn something :: aaa111\n' >> "$tmp/signals/s2.log"
for i in 1 2 3 4 5; do
    out="$(run "$(payload s2)")"
    [[ -z "$out" ]] || { echo "FAIL: escalated with only 1 guard fire (prompt $i): $out"; exit 1; }
done

# --- session s3: no signal log at all → no escalation ---
for i in 1 2 3 4; do
    out="$(run "$(payload s3)")"
    [[ -z "$out" ]] || { echo "FAIL: escalated with no signal log (prompt $i): $out"; exit 1; }
done

echo "PASS test_struggle_escalation"
