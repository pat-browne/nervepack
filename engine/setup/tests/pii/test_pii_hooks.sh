#!/usr/bin/env bash
# Integration tests: episodic-recall (Python port, dispatched via cli.py) and
# lesson-recall.sh filter PII from injected context when pii_filter toggle is
# on; pass through unchanged when off.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$HERE/../.."
CLI="$S/../nervepack_engine/cli.py"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

# --- shared toggle env ---
ON_CONF="$tmp/toggles_on.conf"
OFF_CONF="$tmp/toggles_off.conf"
printf 'memory|shared|runtime|on|\npii_filter|shared|runtime|on|\n'  > "$ON_CONF"
printf 'memory|shared|runtime|on|\npii_filter|shared|runtime|off|\n' > "$OFF_CONF"

# --- episodic fixture with PII in body ---
mkdir -p "$tmp/episodic"
cat > "$tmp/episodic/INDEX.md" <<'IDX'
| topic | last_updated | keywords | lines |
|---|---|---|---:|
| pii-topic | 2026-07-01 | pii, auth | 5 |
IDX
cat > "$tmp/episodic/pii-topic.md" <<'TOP'
---
name: pii-topic
kind: episodic
---
# PII topic
Contact admin@example.com at 192.168.1.5 for access.
TOP

ep_payload="$(jq -nc '{session_id:"s1", prompt:"fix the pii auth bug"}')"
ep_run() {
  printf '%s' "$ep_payload" | \
    NP_TOGGLES_CONF="$1" EPISODIC_DIR="$tmp/episodic" EPISODIC_STATE_DIR="$tmp/state-$2" \
    python3 "$CLI" hook episodic-recall
}

# --- episodic: pii_filter ON -> email and IP scrubbed ---
out_on="$(ep_run "$ON_CONF" on)"
echo "$out_on" | jq -e '.hookSpecificOutput.additionalContext | test("pii-topic")' >/dev/null \
  || { echo "FAIL: episodic pii=on: topic not injected: $out_on"; exit 1; }
echo "$out_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q 'admin@example.com' \
  && { echo "FAIL: episodic pii=on: raw email leaked"; exit 1; }
echo "$out_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q '192\.168\.1\.5' \
  && { echo "FAIL: episodic pii=on: raw IP leaked"; exit 1; }
echo "$out_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q '\[EMAIL\]' \
  || { echo "FAIL: episodic pii=on: [EMAIL] placeholder missing"; exit 1; }

# --- episodic: pii_filter OFF -> raw content unchanged ---
out_off="$(ep_run "$OFF_CONF" off)"
echo "$out_off" | jq -r '.hookSpecificOutput.additionalContext' | grep -q 'admin@example.com' \
  || { echo "FAIL: episodic pii=off: email was unexpectedly filtered"; exit 1; }

# --- lesson fixture with PII in body ---
mkdir -p "$tmp/lessons"
cat > "$tmp/lessons/INDEX.md" <<'IDX'
| topic | tool_match | gate | triggers |
|---|---|---|---|
| pii-lesson |  | off | pii,auth |
IDX
cat > "$tmp/lessons/pii-lesson.md" <<'LESSON'
---
provenance: failure
---
**Symptom:** user@secret.org called 10.0.0.1
**Why:** PII in lessons
**Do:** redact before storing
LESSON

ls_payload="$(jq -nc '{session_id:"s2", prompt:"fix pii auth issue"}')"
ls_run() {
  printf '%s' "$ls_payload" | \
    NP_TOGGLES_CONF="$1" EPISODIC_LESSON_DIR="$tmp/lessons" EPISODIC_STATE_DIR="$tmp/ls-state-$2" \
    bash "$S/lesson-recall.sh"
}

# --- lesson: pii_filter ON -> email and IP scrubbed ---
out_ls_on="$(ls_run "$ON_CONF" on)"
echo "$out_ls_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q 'user@secret.org' \
  && { echo "FAIL: lesson pii=on: raw email leaked"; exit 1; }
echo "$out_ls_on" | jq -r '.hookSpecificOutput.additionalContext' | grep -q '10\.0\.0\.1' \
  && { echo "FAIL: lesson pii=on: raw IP leaked"; exit 1; }

# --- lesson: pii_filter OFF -> raw content unchanged ---
out_ls_off="$(ls_run "$OFF_CONF" off)"
echo "$out_ls_off" | jq -r '.hookSpecificOutput.additionalContext' | grep -q 'user@secret.org' \
  || { echo "FAIL: lesson pii=off: content was unexpectedly filtered"; exit 1; }

echo "PASS test_pii_hooks"
