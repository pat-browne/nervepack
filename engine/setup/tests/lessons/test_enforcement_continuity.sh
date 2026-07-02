#!/usr/bin/env bash
# np-test: lessons | enforcement-continuity
# Enforcement-continuity test for the lessons-layer merge (Phase 1 Task 2 /
# Phase 2 Task 3): lesson-guard.sh (renamed from playbook-guard.sh) must keep
# firing PreToolUse "ask" gates for enforced (provenance: failure) lessons read
# from memory/lessons/, and must NOT fire for advisory (provenance: success,
# no enforce block) lessons -- the empty-tool_match-cell skip in INDEX.md is
# the advisory-vs-enforced distinction and must survive the playbooks+
# strategies -> lessons merge.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$HERE/../../lesson-guard.sh"

command -v jq >/dev/null || { echo "SKIP: jq not available"; exit 0; }

tmp="$(mktemp -d)"; st="$(mktemp -d)"; trap 'rm -rf "$tmp" "$st"' EXIT
mkdir -p "$tmp/memory/lessons"

# Enforced (failure) lesson: fires an "ask" gate for a matching Bash command.
cat > "$tmp/memory/lessons/git.md" <<'LESSON'
---
name: grep combined short flags get silently misread
kind: lesson
provenance: failure
status: confirmed
seen: 5
last_updated: 2026-06-01
topic_triggers: [git]
enforce:
  tool_match: "grep -[a-z]*l[a-z]*i"
  gate: ask
wiki: []
---
**Symptom:** combined short grep flags like -lin are easy to misread.
**Do:** prefer separate long-form flags in scripted/wrapped contexts.
LESSON

# Advisory (success) lesson: NO enforce block -> empty tool_match cell in
# INDEX.md -> must be skipped regardless of command (advisory-only).
cat > "$tmp/memory/lessons/refactor.md" <<'LESSON'
---
name: prefer small surgical diffs over broad rewrites
kind: lesson
provenance: success
status: confirmed
seen: 3
last_updated: 2026-06-01
topic_triggers: [refactor]
wiki: []
---
**Why:** small diffs are easier to review and bisect.
**Do:** land the smallest change that satisfies the requirement.
LESSON

cat > "$tmp/memory/lessons/INDEX.md" <<'IDX'
| topic | tool_match | gate | topic_triggers |
|---|---|---|---|
| git | grep -[a-z]*l[a-z]*i | ask | git |
| refactor |  |  | refactor |
IDX

run() {  # $1=payload json
  printf '%s' "$1" | NP_CONTENT_DIR="$tmp" EPISODIC_STATE_DIR="$st" bash "$GUARD"
}

# Case 1: enforced failure-provenance lesson fires "ask" for a matching command.
out1="$(run "$(jq -nc '{tool_name:"Bash",tool_input:{command:"grep -lin foo"},session_id:"t"}')")"
echo "$out1" | jq -e '.hookSpecificOutput.permissionDecision == "ask"' >/dev/null \
  || { echo "FAIL: enforced failure lesson did not ask: $out1"; exit 1; }
echo "$out1" | jq -e '.hookSpecificOutput.permissionDecisionReason | test("combined short grep flags")' >/dev/null \
  || { echo "FAIL: ask reason missing lesson body: $out1"; exit 1; }

# Case 2: advisory success-provenance lesson (no enforce block, empty
# tool_match cell) must NOT fire for any command -- decision empty/allow.
out2="$(run "$(jq -nc '{tool_name:"Bash",tool_input:{command:"npm test"},session_id:"t2"}')")"
[[ -z "$out2" ]] || { echo "FAIL: advisory success lesson fired (expected silent no-op): $out2"; exit 1; }

# Case 3: the toggle gate -- `lessons.enforce=off` must silence an otherwise-
# matching enforced lesson (the enforce switch called out in the brief).
local_conf="$tmp/toggles.local"
echo "lessons.enforce=off" > "$local_conf"
out3="$(printf '%s' "$(jq -nc '{tool_name:"Bash",tool_input:{command:"grep -lin foo"},session_id:"t3"}')" \
  | NP_CONTENT_DIR="$tmp" EPISODIC_STATE_DIR="$st" NP_TOGGLES_LOCAL="$local_conf" bash "$GUARD")"
[[ -z "$out3" ]] || { echo "FAIL: lessons.enforce=off did not silence the guard: $out3"; exit 1; }

# Case 4: `lessons=off` (whole feature off) must also silence it.
echo "lessons=off" > "$local_conf"
out4="$(printf '%s' "$(jq -nc '{tool_name:"Bash",tool_input:{command:"grep -lin foo"},session_id:"t4"}')" \
  | NP_CONTENT_DIR="$tmp" EPISODIC_STATE_DIR="$st" NP_TOGGLES_LOCAL="$local_conf" bash "$GUARD")"
[[ -z "$out4" ]] || { echo "FAIL: lessons=off did not silence the guard: $out4"; exit 1; }

echo "PASS test_enforcement_continuity"
